from __future__ import annotations

"""Durable sidecar implementation of the bounded crawl-batch port.

The sidecar is deliberately additive: it never opens or mutates the M7
``crawl_state.sqlite3`` database.  All mutations are serialized by the M7
writer lock and each transition is a single SQLite transaction.
"""

import hashlib
import json
import math
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Iterator

from knowledgenexus.foundation.domain.models.confluence_crawl_batch import (
    BatchCheckpoint, BatchFailureCategory, BatchLease, BatchMetrics, BatchRequest,
    BatchState,
)
from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import InventoryOccurrence
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId, CanonicalIncludeRoots
from knowledgenexus.foundation.domain.models.confluence_page_metadata import ConfluencePageMetadata
from knowledgenexus.foundation.domain.rules.confluence_batch_retry_policy import is_retryable
from knowledgenexus.foundation.ports.confluence_crawl_batch_port import (
    BatchLeaseConflict,
)
from knowledgenexus.foundation.infrastructure.locking import confluence_crawl_writer_lock as _writer_lock

SCHEMA_IDENTITY = "knowledgenexus.m7.batch-sidecar.v1"
SCHEMA_VERSION = 1
DB_NAME = "batch_state.sqlite3"
_OCCURRENCE_STREAM_DOMAIN = "knowledgenexus.m7.batch-sidecar.occurrence-stream.v2"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_now(value: object) -> float:
    if type(value) not in (int, float) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("now is invalid")
    return float(value)


def _valid_digest(value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("digest is invalid")
    return value


class SQLiteConfluenceCrawlBatchStore:
    """A lock-scoped, crash-safe sidecar store for ``BatchCheckpoint`` rows."""

    def __init__(self, workspace: Path, *, requests: Iterable[BatchRequest] | None = None, writer_lease=None, max_attempts: int = 3):
        if not isinstance(workspace, Path) or not workspace.is_absolute() or any(p in (".", "..") for p in workspace.parts):
            raise ValueError("workspace is invalid")
        if not workspace.is_dir():
            raise ValueError("workspace is invalid")
        self.workspace = workspace
        self.path = workspace / DB_NAME
        self._writer_lease = writer_lease
        if type(max_attempts) is not int or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 100:
            raise ValueError("max_attempts is invalid")
        self.max_attempts = max_attempts
        self._requests: dict[str, BatchRequest] = {}
        if requests is not None:
            values = tuple(requests)
            if any(type(r) is not BatchRequest for r in values):
                raise TypeError("requests are invalid")
            self._requests = {r.batch_id: r for r in values}

    @classmethod
    def initialize(cls, workspace: Path, requests: Iterable[BatchRequest]) -> "SQLiteConfluenceCrawlBatchStore":
        store = cls(workspace, requests=requests)
        if not store._requests:
            raise ValueError("requests are invalid")
        store._validate_requests(tuple(store._requests.values()))
        with store._locked_connection(create=True) as conn:
            store._write_requests(conn, tuple(sorted(store._requests.values(), key=lambda r: r.ordinal)))
        return store

    @staticmethod
    def _validate_requests(requests: tuple[BatchRequest, ...]) -> None:
        if [r.ordinal for r in requests] != list(range(len(requests))):
            raise ValueError("batch ordinals are not contiguous")
        ids = [r.batch_id for r in requests]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate batch identity")
        if requests:
            binding = (requests[0].run_id, requests[0].generation_digest, requests[0].config_digest, requests[0].inventory_digest)
            if any((r.run_id, r.generation_digest, r.config_digest, r.inventory_digest) != binding for r in requests):
                raise ValueError("request identity drift")
        pages = [p.page_id for r in requests for p in r.occurrences]
        if len(pages) != len(set(pages)):
            raise ValueError("duplicate page identity")
        occ = [p.item_ordinal for r in requests for p in r.occurrences]
        if occ != list(range(len(occ))):
            raise ValueError("occurrence order drift")
        for request in requests:
            for occurrence in request.occurrences:
                if occurrence.run_id.value != request.run_id:
                    raise ValueError("occurrence run identity drift")

    @contextmanager
    def _locked_connection(self, *, create: bool = False) -> Iterator[sqlite3.Connection]:
        lease = None
        conn = None
        try:
            lease = self._writer_lease or _writer_lock._acquire_writer_lock(self.workspace)
            if self._writer_lease is not None:
                self._writer_lease._verify(allow_sidecar_lifecycle=True)
            if self.path.exists() and (self.path.is_symlink() or not self.path.is_file()):
                raise ValueError("sidecar path is invalid")
            if not create and not self.path.exists():
                raise KeyError("sidecar is not initialized")
            # Only an absent or zero-byte target may be initialized.  Never
            # graft the sidecar schema onto an arbitrary existing database.
            if create and self.path.exists() and self.path.stat().st_size > 0:
                probe = sqlite3.connect(str(self.path), timeout=0.2)
                try:
                    has_metadata = probe.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sidecar_metadata'").fetchone() is not None
                finally:
                    probe.close()
                if not has_metadata:
                    raise ValueError("sidecar target is not a fresh database")
            conn = sqlite3.connect(str(self.path), timeout=0.2)
            conn.execute("PRAGMA foreign_keys=ON")
            self._ensure_schema(conn, initialize=create and not self._has_schema(conn))
            self._validate_binding(conn)
            yield conn
        except sqlite3.Error:
            raise BatchLeaseConflict("sidecar_state") from None
        finally:
            if conn is not None:
                conn.close()
            if lease is not None and self._writer_lease is None:
                lease.close()

    @staticmethod
    def _has_schema(conn: sqlite3.Connection) -> bool:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sidecar_metadata'").fetchone() is not None

    def _ensure_schema(self, conn: sqlite3.Connection, *, initialize: bool = False) -> None:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if not initialize:
            if version != SCHEMA_VERSION:
                raise ValueError("sidecar schema mismatch")
            row = conn.execute("SELECT identity, version FROM sidecar_metadata WHERE singleton=1").fetchone()
            if row != (SCHEMA_IDENTITY, SCHEMA_VERSION):
                raise ValueError("sidecar schema mismatch")
            self._validate_catalog(conn)
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.executescript(
            """CREATE TABLE sidecar_metadata(singleton INTEGER PRIMARY KEY CHECK(singleton=1), identity TEXT NOT NULL, version INTEGER NOT NULL);
            CREATE TABLE batch_runs(singleton INTEGER PRIMARY KEY CHECK(singleton=1), workspace TEXT NOT NULL, run_id TEXT NOT NULL, generation_digest TEXT NOT NULL, config_digest TEXT NOT NULL, inventory_digest TEXT NOT NULL, occurrence_fingerprint TEXT NOT NULL);
            CREATE TABLE batch_requests(ordinal INTEGER PRIMARY KEY, batch_id TEXT NOT NULL UNIQUE, run_id TEXT NOT NULL, generation_digest TEXT NOT NULL, config_digest TEXT NOT NULL, inventory_digest TEXT NOT NULL, page_count INTEGER NOT NULL, occurrence_json TEXT NOT NULL);
            CREATE TABLE batch_pages(batch_id TEXT NOT NULL, occurrence_ordinal INTEGER NOT NULL, page_id TEXT NOT NULL, PRIMARY KEY(batch_id, occurrence_ordinal), UNIQUE(page_id), FOREIGN KEY(batch_id) REFERENCES batch_requests(batch_id));
            CREATE TABLE batch_checkpoints(batch_id TEXT PRIMARY KEY, state TEXT NOT NULL, attempt INTEGER NOT NULL, token TEXT, expires_at REAL, failure_category TEXT, batch_digest TEXT, page_count INTEGER, byte_count INTEGER, request_count INTEGER, retry_count INTEGER, elapsed_seconds REAL, queue_high_watermark INTEGER, peak_rss_bytes INTEGER, FOREIGN KEY(batch_id) REFERENCES batch_requests(batch_id));
            CREATE TABLE batch_attempt_failures(batch_id TEXT NOT NULL, attempt INTEGER NOT NULL, category TEXT NOT NULL, recorded_at REAL NOT NULL, status TEXT NOT NULL, PRIMARY KEY(batch_id, attempt));
            CREATE INDEX idx_batch_pending ON batch_checkpoints(state, batch_id);
            """
            )
            conn.execute("INSERT INTO sidecar_metadata VALUES(1,?,?)", (SCHEMA_IDENTITY, SCHEMA_VERSION))
            conn.execute("PRAGMA user_version=1")
            conn.commit()
            self._validate_catalog(conn)
        except Exception:
            conn.rollback()
            raise

    @staticmethod
    def _validate_catalog(conn: sqlite3.Connection) -> None:
        expected_sql = {
            "sidecar_metadata": "CREATE TABLE sidecar_metadata(singleton INTEGER PRIMARY KEY CHECK(singleton=1), identity TEXT NOT NULL, version INTEGER NOT NULL)",
            "batch_runs": "CREATE TABLE batch_runs(singleton INTEGER PRIMARY KEY CHECK(singleton=1), workspace TEXT NOT NULL, run_id TEXT NOT NULL, generation_digest TEXT NOT NULL, config_digest TEXT NOT NULL, inventory_digest TEXT NOT NULL, occurrence_fingerprint TEXT NOT NULL)",
            "batch_requests": "CREATE TABLE batch_requests(ordinal INTEGER PRIMARY KEY, batch_id TEXT NOT NULL UNIQUE, run_id TEXT NOT NULL, generation_digest TEXT NOT NULL, config_digest TEXT NOT NULL, inventory_digest TEXT NOT NULL, page_count INTEGER NOT NULL, occurrence_json TEXT NOT NULL)",
            "batch_pages": "CREATE TABLE batch_pages(batch_id TEXT NOT NULL, occurrence_ordinal INTEGER NOT NULL, page_id TEXT NOT NULL, PRIMARY KEY(batch_id, occurrence_ordinal), UNIQUE(page_id), FOREIGN KEY(batch_id) REFERENCES batch_requests(batch_id))",
            "batch_checkpoints": "CREATE TABLE batch_checkpoints(batch_id TEXT PRIMARY KEY, state TEXT NOT NULL, attempt INTEGER NOT NULL, token TEXT, expires_at REAL, failure_category TEXT, batch_digest TEXT, page_count INTEGER, byte_count INTEGER, request_count INTEGER, retry_count INTEGER, elapsed_seconds REAL, queue_high_watermark INTEGER, peak_rss_bytes INTEGER, FOREIGN KEY(batch_id) REFERENCES batch_requests(batch_id))",
            "batch_attempt_failures": "CREATE TABLE batch_attempt_failures(batch_id TEXT NOT NULL, attempt INTEGER NOT NULL, category TEXT NOT NULL, recorded_at REAL NOT NULL, status TEXT NOT NULL, PRIMARY KEY(batch_id, attempt))",
            "idx_batch_pending": "CREATE INDEX idx_batch_pending ON batch_checkpoints(state, batch_id)",
        }
        def compact(sql: str) -> str:
            return " ".join(sql.replace("\n", " ").split()).lower()
        expected_tables = {
            "sidecar_metadata": [("singleton", "INTEGER", 0, None, 1), ("identity", "TEXT", 1, None, 0), ("version", "INTEGER", 1, None, 0)],
            "batch_runs": [("singleton", "INTEGER", 0, None, 1), ("workspace", "TEXT", 1, None, 0), ("run_id", "TEXT", 1, None, 0), ("generation_digest", "TEXT", 1, None, 0), ("config_digest", "TEXT", 1, None, 0), ("inventory_digest", "TEXT", 1, None, 0), ("occurrence_fingerprint", "TEXT", 1, None, 0)],
            "batch_requests": [("ordinal", "INTEGER", 0, None, 1), ("batch_id", "TEXT", 1, None, 0), ("run_id", "TEXT", 1, None, 0), ("generation_digest", "TEXT", 1, None, 0), ("config_digest", "TEXT", 1, None, 0), ("inventory_digest", "TEXT", 1, None, 0), ("page_count", "INTEGER", 1, None, 0), ("occurrence_json", "TEXT", 1, None, 0)],
            "batch_pages": [("batch_id", "TEXT", 1, None, 1), ("occurrence_ordinal", "INTEGER", 1, None, 2), ("page_id", "TEXT", 1, None, 0)],
            "batch_checkpoints": [("batch_id", "TEXT", 0, None, 1), ("state", "TEXT", 1, None, 0), ("attempt", "INTEGER", 1, None, 0), ("token", "TEXT", 0, None, 0), ("expires_at", "REAL", 0, None, 0), ("failure_category", "TEXT", 0, None, 0), ("batch_digest", "TEXT", 0, None, 0), ("page_count", "INTEGER", 0, None, 0), ("byte_count", "INTEGER", 0, None, 0), ("request_count", "INTEGER", 0, None, 0), ("retry_count", "INTEGER", 0, None, 0), ("elapsed_seconds", "REAL", 0, None, 0), ("queue_high_watermark", "INTEGER", 0, None, 0), ("peak_rss_bytes", "INTEGER", 0, None, 0)],
            "batch_attempt_failures": [("batch_id", "TEXT", 1, None, 1), ("attempt", "INTEGER", 1, None, 2), ("category", "TEXT", 1, None, 0), ("recorded_at", "REAL", 1, None, 0), ("status", "TEXT", 1, None, 0)],
        }
        actual_tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if actual_tables != set(expected_tables): raise ValueError("sidecar catalog mismatch")
        for name, expected in expected_sql.items():
            row = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
            if row is None or compact(row[0]) != compact(expected): raise ValueError("sidecar catalog mismatch")
        for table, expected in expected_tables.items():
            actual = [(r[1], r[2], r[3], r[4], r[5]) for r in conn.execute(f"PRAGMA table_info({table})")]
            if actual != [(n, t, nn, d, pk) for n, t, nn, d, pk in expected]: raise ValueError("sidecar catalog mismatch")
        indexes = {r[1]: (r[2], r[3], r[4]) for r in conn.execute("PRAGMA index_list(batch_requests)")}
        if "sqlite_autoindex_batch_requests_1" not in indexes: raise ValueError("sidecar catalog mismatch")
        if [r[2] for r in conn.execute("PRAGMA index_info(sqlite_autoindex_batch_requests_1)")] != ["batch_id"]: raise ValueError("sidecar catalog mismatch")
        idx = conn.execute("PRAGMA index_list(batch_checkpoints)").fetchall()
        named = {r[1] for r in idx if not r[1].startswith("sqlite_")}
        if named != {"idx_batch_pending"} or tuple(r[2] for r in idx if r[1] == "idx_batch_pending") != (0,): raise ValueError("sidecar catalog mismatch")
        if [r[2] for r in conn.execute("PRAGMA index_info(idx_batch_pending)")] != ["state", "batch_id"]: raise ValueError("sidecar catalog mismatch")
        expected_fks = [(0, 0, "batch_requests", "batch_id", "batch_id", "NO ACTION", "NO ACTION", "NONE")]
        for table in ("batch_pages", "batch_checkpoints"):
            fks = [tuple(r[:8]) for r in conn.execute(f"PRAGMA foreign_key_list({table})")]
            if fks != expected_fks: raise ValueError("sidecar catalog mismatch")
        objects = {r[1] for r in conn.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
        if objects != set(expected_tables) | {"idx_batch_pending"}: raise ValueError("sidecar catalog mismatch")

    def _validate_binding(self, conn: sqlite3.Connection) -> None:
        self._validate_catalog(conn)
        row = conn.execute("SELECT workspace,run_id,generation_digest,config_digest,inventory_digest,occurrence_fingerprint FROM batch_runs WHERE singleton=1").fetchone()
        if row is None:
            # initialize() validates and writes the singleton binding in the
            # same lock scope immediately after schema creation.
            if self._requests and not conn.execute("SELECT 1 FROM batch_requests LIMIT 1").fetchone():
                return
            raise ValueError("sidecar binding mismatch")
        if row[0] != str(self.workspace): raise ValueError("sidecar binding mismatch")
        persisted = self._load_requests(conn)
        # Once the singleton binding exists, the request stream is immutable
        # and must never disappear.  The only empty-stream exception is the
        # first initialization transaction handled above, before the binding
        # singleton is written.
        if not persisted:
            raise ValueError("sidecar binding mismatch")
        first = persisted[0]
        expected_fp = self._occurrence_stream_digest(persisted)
        if row[1:5] != (first.run_id, first.generation_digest, first.config_digest, first.inventory_digest) or row[5] != expected_fp:
            raise ValueError("sidecar binding mismatch")
        if self._requests:
            supplied = tuple(sorted(self._requests.values(), key=lambda r: r.ordinal))
            self._validate_requests(supplied)
            if persisted != supplied: raise BatchLeaseConflict("identity_conflict")

    @staticmethod
    def _encode_occurrence(o: InventoryOccurrence) -> dict:
        m = o.metadata
        return {"run_id": str(o.run_id), "include_root_ordinal": o.include_root_ordinal, "include_root_page_id": o.include_root_page_id, "window_start": o.window_start, "item_ordinal": o.item_ordinal, "page_id": o.page_id, "include_roots": list(o.include_roots.root_ids), "metadata": {k: getattr(m, k) for k in ("page_id", "title", "space_key", "parent_page_id", "ancestor_page_ids", "ancestor_titles", "updated_at", "source_version", "labels", "attachment_count")}}

    @classmethod
    def _canonical_occurrence(cls, batch_ordinal: int, occurrence: InventoryOccurrence) -> dict:
        """Return the complete, typed identity payload for stream hashing."""
        encoded = cls._encode_occurrence(occurrence)
        return {
            "type": "inventory_occurrence",
            "batch_ordinal": batch_ordinal,
            "occurrence": encoded,
        }

    @classmethod
    def _occurrence_stream_digest(cls, requests: tuple[BatchRequest, ...]) -> str:
        records = [
            cls._canonical_occurrence(request.ordinal, occurrence)
            for request in requests
            for occurrence in request.occurrences
        ]
        payload = _OCCURRENCE_STREAM_DOMAIN + "\x00" + json.dumps(
            records, separators=(",", ":"), sort_keys=True, ensure_ascii=False
        )
        return _digest(payload)

    @staticmethod
    def _decode_occurrence(value: object) -> InventoryOccurrence:
        if type(value) is not dict or set(value) != {"run_id", "include_root_ordinal", "include_root_page_id", "window_start", "item_ordinal", "page_id", "include_roots", "metadata"} or type(value["metadata"]) is not dict: raise ValueError("occurrence data is invalid")
        md = value["metadata"]
        fields = ("page_id", "title", "space_key", "parent_page_id", "ancestor_page_ids", "ancestor_titles", "updated_at", "source_version", "labels", "attachment_count")
        if set(md) != set(fields): raise ValueError("occurrence metadata is invalid")
        metadata = ConfluencePageMetadata(**{k: tuple(md[k]) if k in ("ancestor_page_ids", "ancestor_titles", "labels") else md[k] for k in fields})
        return InventoryOccurrence(CrawlRunId(value["run_id"]), value["include_root_ordinal"], value["include_root_page_id"], value["window_start"], value["item_ordinal"], value["page_id"], metadata, CanonicalIncludeRoots(tuple(value["include_roots"])))

    def _load_requests(self, conn: sqlite3.Connection) -> tuple[BatchRequest, ...]:
        rows = conn.execute("SELECT ordinal,batch_id,run_id,generation_digest,config_digest,inventory_digest,page_count,occurrence_json FROM batch_requests ORDER BY ordinal").fetchall()
        values = []
        for ordinal, batch_id, run_id, generation, config, inventory, page_count, encoded in rows:
            try:
                raw = json.loads(encoded)
                occurrences = tuple(self._decode_occurrence(x) for x in raw)
                canonical = json.dumps(
                    [self._encode_occurrence(item) for item in occurrences],
                    separators=(",", ":"), sort_keys=True, ensure_ascii=False,
                )
                if type(encoded) is not str or encoded != canonical:
                    raise ValueError("noncanonical occurrence data")
            except Exception as exc: raise ValueError("persisted request is invalid") from exc
            request = BatchRequest(run_id, generation, config, inventory, ordinal, occurrences)
            if request.batch_id != batch_id or page_count != len(occurrences): raise ValueError("persisted request identity mismatch")
            page_rows = conn.execute("SELECT occurrence_ordinal,page_id FROM batch_pages WHERE batch_id=? ORDER BY occurrence_ordinal", (batch_id,)).fetchall()
            if [(o, p) for o, p in page_rows] != [(o.item_ordinal, o.page_id) for o in occurrences]: raise ValueError("persisted page identity mismatch")
            values.append(request)
        if values: self._validate_requests(tuple(values))
        return tuple(values)

    def _write_requests(self, conn: sqlite3.Connection, requests: tuple[BatchRequest, ...]) -> None:
        if not requests:
            raise ValueError("requests are invalid")
        first = requests[0]
        fingerprint = self._occurrence_stream_digest(requests)
        conn.execute("INSERT OR IGNORE INTO batch_runs VALUES(1,?,?,?,?,?,?)", (str(self.workspace), first.run_id, first.generation_digest, first.config_digest, first.inventory_digest, fingerprint))
        binding = conn.execute("SELECT workspace,run_id,generation_digest,config_digest,inventory_digest,occurrence_fingerprint FROM batch_runs WHERE singleton=1").fetchone()
        expected = (str(self.workspace), first.run_id, first.generation_digest, first.config_digest, first.inventory_digest, fingerprint)
        if binding != expected:
            raise ValueError("sidecar binding conflict")
        for request in requests:
            existing = conn.execute("SELECT batch_id,occurrence_json FROM batch_requests WHERE ordinal=?", (request.ordinal,)).fetchone()
            pages = [p.page_id for p in request.occurrences]
            encoded = json.dumps([self._encode_occurrence(p) for p in request.occurrences], separators=(",", ":"), sort_keys=True)
            if existing is not None and existing != (request.batch_id, encoded):
                raise BatchLeaseConflict("identity_conflict")
            conn.execute("INSERT OR IGNORE INTO batch_requests VALUES(?,?,?,?,?,?,?,?)", (request.ordinal, request.batch_id, request.run_id, request.generation_digest, request.config_digest, request.inventory_digest, len(pages), encoded))
            for occurrence in request.occurrences:
                conn.execute("INSERT OR IGNORE INTO batch_pages VALUES(?,?,?)", (request.batch_id, occurrence.item_ordinal, occurrence.page_id))
            conn.execute("INSERT OR IGNORE INTO batch_checkpoints(batch_id,state,attempt) VALUES(?,?,0)", (request.batch_id, BatchState.PENDING.value))
        conn.commit()

    def create(self, checkpoint: BatchCheckpoint) -> BatchCheckpoint:
        if type(checkpoint) is not BatchCheckpoint:
            raise TypeError("checkpoint is invalid")
        with self._locked_connection() as conn:
            row = conn.execute("SELECT state,attempt,token,expires_at,failure_category,batch_digest,page_count,byte_count,request_count,retry_count,elapsed_seconds,queue_high_watermark,peak_rss_bytes FROM batch_checkpoints WHERE batch_id=?", (checkpoint.request.batch_id,)).fetchone()
            if row is None:
                self._write_requests(conn, (checkpoint.request,)); return checkpoint
            current = self._row_checkpoint(conn, checkpoint.request.batch_id, row)
            if current != checkpoint:
                raise BatchLeaseConflict("identity_conflict")
            return current

    def _row_request(self, conn, batch_id: str) -> BatchRequest:
        request = self._requests.get(batch_id)
        if request is not None:
            return request
        row = conn.execute("SELECT ordinal,batch_id,run_id,generation_digest,config_digest,inventory_digest,page_count,occurrence_json FROM batch_requests WHERE batch_id=?", (batch_id,)).fetchone()
        if row is None:
            raise KeyError(batch_id)
        ordinal, persisted_id, run_id, generation, config, inventory, page_count, encoded = row
        try:
            occurrences = tuple(self._decode_occurrence(x) for x in json.loads(encoded))
            request = BatchRequest(run_id, generation, config, inventory, ordinal, occurrences)
        except Exception as exc:
            raise ValueError("persisted request is invalid") from exc
        if request.batch_id != persisted_id or page_count != len(occurrences):
            raise ValueError("persisted request identity mismatch")
        return request

    def _row_checkpoint(self, conn, batch_id: str, row=None) -> BatchCheckpoint:
        if row is None:
            row = conn.execute("SELECT state,attempt,token,expires_at,failure_category,batch_digest,page_count,byte_count,request_count,retry_count,elapsed_seconds,queue_high_watermark,peak_rss_bytes FROM batch_checkpoints WHERE batch_id=?", (batch_id,)).fetchone()
        if row is None: raise KeyError(batch_id)
        request = self._row_request(conn, batch_id)
        self._validate_checkpoint_row(conn, batch_id, row, request)
        state = BatchState(row[0]); attempt = row[1]; lease = None
        if state is BatchState.LEASED:
            lease = BatchLease(batch_id, row[2], float(row[3]), attempt, batch_id)
        metrics = None
        if state is BatchState.COMMITTED:
            metrics = BatchMetrics(*row[6:13])
        category = BatchFailureCategory(row[4]) if row[4] is not None else None
        return BatchCheckpoint(request, state, lease, attempt, category, row[5], metrics)

    @staticmethod
    def _validate_checkpoint_row(conn: sqlite3.Connection, batch_id: str, row: tuple, request: BatchRequest) -> None:
        """Validate raw SQLite checkpoint values before domain construction."""
        if type(row) is not tuple or len(row) != 13:
            raise ValueError("checkpoint row is invalid")
        (state, attempt, token, expires_at, failure_category, digest,
         page_count, byte_count, request_count, retry_count,
         elapsed_seconds, queue_high_watermark, peak_rss_bytes) = row
        if type(state) is not str or state not in {s.value for s in BatchState}:
            raise ValueError("checkpoint state is invalid")
        if type(attempt) is not int or isinstance(attempt, bool) or attempt < 0:
            raise ValueError("checkpoint attempt is invalid")
        state_value = BatchState(state)
        metric_values = (page_count, byte_count, request_count, retry_count, queue_high_watermark)

        def null_metrics() -> bool:
            return all(value is None for value in (digest, page_count, byte_count,
                                                    request_count, retry_count,
                                                    elapsed_seconds,
                                                    queue_high_watermark,
                                                    peak_rss_bytes))

        if state_value is BatchState.PENDING:
            if attempt != 0 or token is not None or expires_at is not None or failure_category is not None or not null_metrics():
                raise ValueError("pending checkpoint is incoherent")
            return
        if state_value is BatchState.LEASED:
            if attempt <= 0 or type(token) is not str or not token:
                raise ValueError("leased checkpoint token is invalid")
            if type(expires_at) not in (int, float) or isinstance(expires_at, bool) or not math.isfinite(expires_at) or expires_at <= 0:
                raise ValueError("leased checkpoint expiry is invalid")
            if failure_category is not None or not null_metrics():
                raise ValueError("leased checkpoint is incoherent")
            return
        if state_value is BatchState.FAILED:
            if attempt <= 0 or token is not None or expires_at is not None or digest is not None or not null_metrics():
                raise ValueError("failed checkpoint is incoherent")
            if type(failure_category) is not str or failure_category not in {c.value for c in BatchFailureCategory}:
                raise ValueError("failure category is invalid")
            return
        # COMMITTED: all metric columns are populated and coherent with the
        # request and attempt history; peak RSS remains nullable by design.
        if attempt <= 0 or token is not None or expires_at is not None or failure_category is not None:
            raise ValueError("committed checkpoint is incoherent")
        _valid_digest(digest)
        if type(page_count) is not int or isinstance(page_count, bool) or page_count != len(request.occurrences):
            raise ValueError("committed page count is invalid")
        if type(request_count) is not int or isinstance(request_count, bool) or request_count != page_count:
            raise ValueError("committed request count is invalid")
        for value in (byte_count, retry_count, queue_high_watermark):
            if type(value) is not int or isinstance(value, bool) or value < 0:
                raise ValueError("committed metric counter is invalid")
        if type(elapsed_seconds) not in (int, float) or isinstance(elapsed_seconds, bool) or not math.isfinite(elapsed_seconds) or elapsed_seconds < 0:
            raise ValueError("committed elapsed time is invalid")
        if peak_rss_bytes is not None and (type(peak_rss_bytes) is not int or isinstance(peak_rss_bytes, bool) or peak_rss_bytes < 0):
            raise ValueError("committed RSS metric is invalid")
        if queue_high_watermark > 1 or retry_count > attempt - 1:
            raise ValueError("committed metrics are incoherent")

    def get(self, batch_id: str) -> BatchCheckpoint:
        if type(batch_id) is not str or not batch_id: raise ValueError("batch_id is invalid")
        with self._locked_connection() as conn: return self._row_checkpoint(conn, batch_id)

    def list_next_pending(self, limit: int, after_ordinal: int | None = None) -> tuple[BatchCheckpoint, ...]:
        if type(limit) is not int or isinstance(limit, bool) or limit < 0: raise ValueError("limit is invalid")
        if after_ordinal is not None and (type(after_ordinal) is not int or isinstance(after_ordinal, bool) or after_ordinal < -1): raise ValueError("cursor is invalid")
        with self._locked_connection() as conn:
            rows = conn.execute("SELECT c.batch_id FROM batch_checkpoints c JOIN batch_requests r ON r.batch_id=c.batch_id WHERE c.state='pending' AND r.ordinal>? ORDER BY r.ordinal LIMIT ?", (after_ordinal if after_ordinal is not None else -1, limit)).fetchall()
            return tuple(self._row_checkpoint(conn, r[0]) for r in rows)

    def claim(self, batch_id: str, *, token: str, now: float, lease_seconds: float) -> BatchLease:
        if type(batch_id) is not str or not batch_id or type(token) is not str or not token: raise ValueError("lease request is invalid")
        now = _valid_now(now)
        if type(lease_seconds) not in (int,float) or isinstance(lease_seconds, bool) or not math.isfinite(lease_seconds) or lease_seconds <= 0: raise ValueError("lease request is invalid")
        with self._locked_connection() as conn:
            current = self._row_checkpoint(conn, batch_id)
            if current.state in (BatchState.COMMITTED, BatchState.FAILED) or (current.state is BatchState.LEASED and current.lease and current.lease.expires_at > now): raise BatchLeaseConflict("already_leased")
            if current.state is BatchState.LEASED and current.lease and current.lease.token == token: raise BatchLeaseConflict("reclaim_token_reuse")
            previous = conn.execute("SELECT COALESCE(MAX(attempt), 0) FROM batch_attempt_failures WHERE batch_id=?", (batch_id,)).fetchone()[0]
            next_attempt = max(current.attempt, previous) + 1
            if next_attempt > self.max_attempts:
                # An expired lease consumes its attempt.  Fence the batch in a
                # terminal state instead of handing out an over-bound lease.
                try:
                    conn.execute("UPDATE batch_checkpoints SET state='failed',attempt=?,token=NULL,expires_at=NULL,failure_category=?,batch_digest=NULL,page_count=NULL,byte_count=NULL,request_count=NULL,retry_count=NULL,elapsed_seconds=NULL,queue_high_watermark=NULL,peak_rss_bytes=NULL WHERE batch_id=?", (current.attempt, BatchFailureCategory.TIMEOUT.value, batch_id))
                    conn.execute("INSERT OR REPLACE INTO batch_attempt_failures VALUES(?,?,?,?,?)", (batch_id, current.attempt, BatchFailureCategory.TIMEOUT.value, now, BatchState.FAILED.value))
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                raise BatchLeaseConflict("max_attempts_exceeded")
            lease = BatchLease(batch_id, token, now + float(lease_seconds), next_attempt, batch_id)
            try:
                conn.execute("UPDATE batch_checkpoints SET state='leased',attempt=?,token=?,expires_at=?,failure_category=NULL WHERE batch_id=?", (lease.attempt, token, lease.expires_at, batch_id))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            return lease

    @staticmethod
    def _validate_commit_metrics(metrics: BatchMetrics, request: BatchRequest, attempt: int) -> None:
        """Fail closed on metrics that the checkpoint row cannot represent."""
        if type(metrics) is not BatchMetrics:
            raise TypeError("metrics are invalid")
        if type(attempt) is not int or isinstance(attempt, bool) or attempt <= 0:
            raise ValueError("lease attempt is invalid")
        if type(metrics.page_count) is not int or isinstance(metrics.page_count, bool) or metrics.page_count != len(request.occurrences):
            raise ValueError("metrics page count is invalid")
        if type(metrics.request_count) is not int or isinstance(metrics.request_count, bool) or metrics.request_count != metrics.page_count:
            raise ValueError("metrics request count is invalid")
        for value in (metrics.byte_count, metrics.retry_count, metrics.queue_high_watermark):
            if type(value) is not int or isinstance(value, bool) or value < 0:
                raise ValueError("metrics counter is invalid")
        if type(metrics.elapsed_seconds) not in (int, float) or isinstance(metrics.elapsed_seconds, bool) or not math.isfinite(metrics.elapsed_seconds) or metrics.elapsed_seconds < 0:
            raise ValueError("elapsed_seconds is invalid")
        if metrics.peak_rss_bytes is not None and (type(metrics.peak_rss_bytes) is not int or isinstance(metrics.peak_rss_bytes, bool) or metrics.peak_rss_bytes < 0):
            raise ValueError("peak RSS metric is invalid")
        if metrics.queue_high_watermark > 1 or metrics.retry_count > attempt - 1:
            raise ValueError("metrics are incoherent")

    def _mutate_lease(self, lease: BatchLease, now: float, action: str, **values):
        if type(lease) is not BatchLease: raise TypeError("lease is invalid")
        now = _valid_now(now)
        with self._locked_connection() as conn:
            current = self._row_checkpoint(conn, lease.batch_id)
            if action == "commit" and current.state is BatchState.COMMITTED:
                digest = _valid_digest(values["batch_digest"])
                metrics = values["metrics"]
                if current.batch_digest != digest or current.metrics != metrics:
                    raise BatchLeaseConflict("digest_conflict")
                return current
            if current.state is not BatchState.LEASED or current.lease != lease or lease.expires_at <= now: raise BatchLeaseConflict("stale_lease")
            if action == "renew":
                expires = now + values["lease_seconds"]; conn.execute("UPDATE batch_checkpoints SET expires_at=? WHERE batch_id=?", (expires, lease.batch_id)); conn.commit(); return replace(lease, expires_at=expires)
            if action == "commit":
                digest = _valid_digest(values["batch_digest"]); metrics = values["metrics"]
                self._validate_commit_metrics(metrics, current.request, lease.attempt)
                try:
                    conn.execute("UPDATE batch_checkpoints SET state='committed',token=NULL,expires_at=NULL,batch_digest=?,page_count=?,byte_count=?,request_count=?,retry_count=?,elapsed_seconds=?,queue_high_watermark=?,peak_rss_bytes=? WHERE batch_id=?", (digest, metrics.page_count, metrics.byte_count, metrics.request_count, metrics.retry_count, metrics.elapsed_seconds, metrics.queue_high_watermark, metrics.peak_rss_bytes, lease.batch_id))
                    committed = self._row_checkpoint(conn, lease.batch_id)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                return committed
            category = values["category"]
            if not isinstance(category, BatchFailureCategory): raise TypeError("category is invalid")
            if action == "requeue" and is_retryable(category) and lease.attempt < self.max_attempts:
                target = "pending"
                # PENDING is a clean retry point; failure data belongs only in
                # the append-only attempt history.
                failure_value = None
            else:
                target = "failed"
                failure_value = category.value
            next_attempt = 0 if target == "pending" else lease.attempt
            conn.execute("UPDATE batch_checkpoints SET state=?,attempt=?,token=NULL,expires_at=NULL,failure_category=?,batch_digest=NULL,page_count=NULL,byte_count=NULL,request_count=NULL,retry_count=NULL,elapsed_seconds=NULL,queue_high_watermark=NULL,peak_rss_bytes=NULL WHERE batch_id=?", (target, next_attempt, failure_value, lease.batch_id));
            conn.execute("INSERT OR REPLACE INTO batch_attempt_failures VALUES(?,?,?,?,?)", (lease.batch_id, lease.attempt, category.value, now, target)); conn.commit(); return self._row_checkpoint(conn, lease.batch_id)

    def renew(self, lease: BatchLease, *, now: float, lease_seconds: float) -> BatchLease:
        if type(lease_seconds) not in (int,float) or isinstance(lease_seconds, bool) or not math.isfinite(lease_seconds) or lease_seconds <= 0: raise ValueError("renew input is invalid")
        return self._mutate_lease(lease, now, "renew", lease_seconds=float(lease_seconds))
    def commit(self, lease: BatchLease, *, batch_digest: str, metrics: BatchMetrics, now: float) -> BatchCheckpoint:
        return self._mutate_lease(lease, now, "commit", batch_digest=batch_digest, metrics=metrics)
    def fail(self, lease: BatchLease, *, category: BatchFailureCategory, now: float) -> BatchCheckpoint:
        return self._mutate_lease(lease, now, "fail", category=category)
    def requeue(self, lease: BatchLease, *, category: BatchFailureCategory, now: float) -> BatchCheckpoint:
        return self._mutate_lease(lease, now, "requeue", category=category)
