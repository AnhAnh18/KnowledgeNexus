"""Sanitized offline operator entry point for a preserved M10 replay."""
from __future__ import annotations

import argparse
import json
import logging
import hashlib
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.m10_snapshot import (
    M10ConfluenceExclusion, M10ConfluenceScope, M10MediaPolicy, M10ProfileIdentity,
    M10SnapshotRequest,
)
from knowledgenexus.foundation.domain.models.m10_composition import M10GitHandoff
from knowledgenexus.foundation.domain.models.one_page_export import OnePageExportProfileBundle

from knowledgenexus.foundation.application.use_cases.export_m10_snapshot import (
    M10SnapshotExportFailure,
)
from knowledgenexus.foundation.infrastructure.exporters.m10_snapshot_exporter import M10FullSnapshotExporter, M10DeltaSnapshotExporter
from knowledgenexus.foundation.infrastructure.exporters.delta_snapshot_reader import PublishedSnapshotReader
from knowledgenexus.foundation.infrastructure.sidecars import DeltaInventoryArtifactStore
from knowledgenexus.foundation.application.use_cases.capture_delta_inventory import selection_identity, scope_identity
from knowledgenexus.foundation.domain.models.delta_inventory import CurrentSelectionPage, DeltaInventoryScope
from knowledgenexus.foundation.domain.models.m10_snapshot import M10SnapshotResult
from knowledgenexus.foundation.domain.models.media_body_materialization import MediaBodyStoreBudget
from knowledgenexus.foundation.domain.models.media_materialization import ConfluenceAttachmentObservation, MediaMaterializationResult, MediaRelationIntent
from knowledgenexus.foundation.application.use_cases.process_confluence_media_batch import ProcessConfluenceMediaBatch
from knowledgenexus.foundation.application.use_cases.process_confluence_media_attachment import ProcessConfluenceMediaAttachment
from knowledgenexus.foundation.application.use_cases.materialize_confluence_media_relations import MaterializeConfluenceMediaRelations
from knowledgenexus.foundation.infrastructure.processors import DrawioProcessor
from knowledgenexus.foundation.infrastructure.raw_store import ConfluenceRawAttachmentStore
from knowledgenexus.foundation.infrastructure.adapters.m10_composition_root import ConfluenceM10CompositionRoot, M10CompositionRootError
from knowledgenexus.foundation.ports.path_safety import require_plain_directory_chain, require_plain_file
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator
from knowledgenexus.foundation.infrastructure.config import load_chunking_profile, load_jira_relation_profile
from knowledgenexus.foundation.infrastructure.raw_store import ConfluenceRawPageGenerationStore
from knowledgenexus.foundation.infrastructure.processors import ConfluenceDataCenterRawPageMapper, ConfluenceStorageXhtmlNormalizer
from knowledgenexus.foundation.infrastructure.tokenization import BgeM3LocalTokenizer
from knowledgenexus.foundation.domain.rules.text_normalization import TextNormalizationRules


EXIT_UNEXPECTED = 1
EXIT_CONFIGURATION = 2
EXIT_INVALID_REQUEST = 20
EXIT_ADAPTER = 21
EXIT_PROJECTION = 15
EXIT_STAGING = 16
EXIT_COMPLETION = 17
EXIT_PUBLICATION = 18
EXIT_ACCEPTANCE = 19

_EXIT_CODES = {
    "invalid_request": EXIT_INVALID_REQUEST,
    "adapter": EXIT_ADAPTER,
    "projection": EXIT_PROJECTION,
    "staging": EXIT_STAGING,
    "completion": EXIT_COMPLETION,
    "publication": EXIT_PUBLICATION,
    "acceptance": EXIT_ACCEPTANCE,
}

_LEAKY_M3_LOGGERS = (
    "knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_writer",
    "knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_completer",
    "knowledgenexus.foundation.infrastructure.exporters.full_snapshot_publisher",
)


def _silence_m3_loggers() -> None:
    for name in _LEAKY_M3_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False


class _ConfigurationError(Exception):
    pass


class _SanitizedParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _ConfigurationError


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _SanitizedParser(prog="export-m10-snapshot", add_help=True)
    parser.add_argument("--raw-generation-root")
    parser.add_argument("--run-id")
    parser.add_argument("--generation-id")
    parser.add_argument("--raw-generation-id")
    parser.add_argument("--chunking-profile")
    parser.add_argument("--tokenizer-assets-dir")
    parser.add_argument("--jira-relation-profile")
    parser.add_argument("--dataset-root")
    parser.add_argument("--ordered-page-id", "--ordered-page-ids", action="append", dest="ordered_page_ids")
    parser.add_argument("--selection-path")
    parser.add_argument("--state-dir")
    parser.add_argument("--processing-state")
    parser.add_argument("--drawio-state")
    parser.add_argument("--space-key", "--space-keys", action="append", dest="space_keys")
    parser.add_argument("--root-page-id", "--root-page-ids", action="append", dest="root_page_ids")
    parser.add_argument("--exclude-page-id", "--exclusions", action="append", dest="excluded_page_ids")
    parser.add_argument("--exclude-ancestor-page-id", action="append", dest="excluded_ancestor_page_ids")
    parser.add_argument("--media-policy", choices=("disabled", "best-effort", "required"), default="disabled")
    parser.add_argument("--git-repository")
    # Identity names the pinned repository; this path identifies the local
    # checkout that may be scanned offline.  Keep them separate so a
    # repository name never becomes an implicit filesystem path.
    parser.add_argument("--git-repository-root")
    parser.add_argument("--git-branch")
    parser.add_argument("--git-commit")
    parser.add_argument("--export-mode", choices=("full_snapshot", "delta"), default="full_snapshot")
    parser.add_argument("--generated-at")
    parser.add_argument("--profile-identity")
    parser.add_argument("--base-dataset-version")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    # Validate supplied filesystem inputs before any producer is constructed.
    directory_options = ("raw_generation_root", "tokenizer_assets_dir", "dataset_root", "git_repository_root", "state_dir")
    file_options = ("chunking_profile", "jira_relation_profile", "selection_path", "processing_state", "drawio_state")
    try:
        for name in directory_options:
            value = getattr(args, name, None)
            if value is not None:
                require_plain_directory_chain(Path(value))
        for name in file_options:
            value = getattr(args, name, None)
            if value is not None:
                path = Path(value)
                if not path.is_absolute():
                    raise ValueError("file path is invalid")
                require_plain_file(path)
    except (OSError, TypeError, ValueError):
        raise _ConfigurationError from None
    return args


def _fail(category: str, code: int) -> int:
    sys.stderr.write(json.dumps({"status": "failed", "category": category}, sort_keys=True, allow_nan=False) + "\n")
    return code


def _media_policy(value: object) -> M10MediaPolicy:
    """Map the small operator vocabulary to the typed M10 policy."""
    if value == "disabled":
        return M10MediaPolicy(False, False, (), 0)
    if value == "best-effort":
        return M10MediaPolicy(True, False, ("failed", "not_processed", "parsed"), 10000)
    if value == "required":
        return M10MediaPolicy(True, True, ("failed", "not_processed", "parsed"), 10000)
    raise _ConfigurationError


class _EmptyGitAdapter:
    """Confluence-only mode still carries the pinned Git identity."""
    def collect(self, request: M10SnapshotRequest) -> M10GitHandoff:
        return M10GitHandoff(
            repository=request.git_repository, branch=request.git_branch,
            commit=request.git_commit, documents=(), chunks=(), relations=(),
            acl=(), media_assets=(), symbols=(), sync_state=(),
        )


_RAW_URI = re.compile(r"^raw://confluence/attachments/(?P<attachment_id>[^/]+)/(?P<content_hash>[0-9a-f]{64})$")


def _relation_media_asset(asset: dict[str, object]) -> dict[str, object]:
    """Project a processed asset to the metadata-only relation model."""
    return {
        **asset,
        "download_status": "not_attempted",
        "processing_status": "not_processed",
        "relevance": "high",
        "extracted_text": None,
        "summary": None,
        "confidence": None,
        "raw_uri": None,
        "content_hash": None,
    }


def _read_state(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise _ConfigurationError from None


def _harness_state(args: argparse.Namespace, run_id: CrawlRunId) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    state_dir = Path(args.state_dir) if args.state_dir else None
    run_state = (state_dir / "runs" / str(run_id)) if state_dir is not None else None
    if state_dir is not None and (state_dir / "inventory-selection.json").exists():
        run_state = state_dir
    selection_path = Path(args.selection_path) if args.selection_path else None
    if selection_path is None and run_state is not None:
        selection_path = run_state / "inventory-selection.json"
    if selection_path is None:
        raise _ConfigurationError
    selection = _read_state(selection_path)
    if type(selection) is not dict or selection.get("format_version") != "confluence-subtree-selection-v1":
        raise _ConfigurationError
    rows = selection.get("items")
    identity = selection.get("selection_identity")
    if selection.get("run_id") != str(run_id) or selection.get("generation_id") != str(run_id) or type(rows) is not list or type(identity) is not str:
        raise _ConfigurationError
    expected_identity = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if identity != expected_identity or not rows:
        raise _ConfigurationError
    for row in rows:
        if type(row) is not dict or set(row) - {"page_id", "crawled_at", "expected_source_version"} or type(row.get("page_id")) is not str or type(row.get("crawled_at")) is not str:
            raise _ConfigurationError
    processing_path = Path(args.processing_state) if args.processing_state else (run_state / "processing-state.json" if run_state else None)
    if processing_path is not None:
        processing = _read_state(processing_path)
        if type(processing) is not dict or processing.get("run_id") != str(run_id) or processing.get("generation_id") != str(run_id) or processing.get("selection_identity") != identity:
            raise _ConfigurationError
        if processing.get("page_count") != len(rows) or processing.get("completed_pages") != len(rows) or processing.get("failed_pages") != 0:
            raise _ConfigurationError
    drawio_path = Path(args.drawio_state) if args.drawio_state else (run_state / "drawio-state.json" if run_state else None)
    assets: list[dict[str, object]] = []
    if drawio_path is not None and drawio_path.exists():
        drawio = _read_state(drawio_path)
        if type(drawio) is not dict or drawio.get("run_id") != str(run_id) or drawio.get("generation_id") != str(run_id) or drawio.get("selection_identity") != identity:
            raise _ConfigurationError
        raw_assets = drawio.get("media_assets")
        if type(raw_assets) is not list or any(type(asset) is not dict for asset in raw_assets):
            raise _ConfigurationError
        assets = raw_assets
    return rows, assets


class _ReplayMediaStage:
    def __init__(self, *, raw_root: Path, assets: list[dict[str, object]], generated_at: str, validator: object, enabled: bool = True) -> None:
        self._assets = tuple(assets) if enabled else ()
        self._generated_at = generated_at
        self._store = None if not self._assets else ConfluenceRawAttachmentStore(
            data_root=raw_root / "attachments",
            budget=MediaBodyStoreBudget(256 * 1024 * 1024, 512 * 1024 * 1024, 0),
        )
        self._batch = ProcessConfluenceMediaBatch(
            processor=ProcessConfluenceMediaAttachment(drawio_processor=DrawioProcessor(), schema_validator=validator)
        )

    def execute(self, *, request: M10SnapshotRequest, **_: object) -> object:
        if not self._assets:
            empty = MediaMaterializationResult(assets=(), relation_intents=())
            return {"media_result": empty, "media_assets": (), "assets": ()}
        items = []
        for asset in self._assets:
            uri = asset.get("raw_uri")
            match = _RAW_URI.fullmatch(uri) if type(uri) is str else None
            if match is None:
                raise _ConfigurationError
            attachment_id, content_hash = match.group("attachment_id"), match.group("content_hash")
            parent_document_id = asset.get("parent_document_id")
            filename = asset.get("filename")
            if type(parent_document_id) is not str or not parent_document_id.startswith("confluence:page:") or type(filename) is not str:
                raise _ConfigurationError
            parent_page_id = parent_document_id.rsplit(":", 1)[-1]
            observation = ConfluenceAttachmentObservation(
                attachment_id=attachment_id, parent_page_id=parent_page_id, filename=filename,
                mime_type=asset.get("mime_type"), size_bytes=asset.get("size_bytes"),
                source_version=asset.get("source_version"), updated_at=asset.get("updated_at"), crawled_at=self._generated_at,
            )
            if self._store is None:
                raise _ConfigurationError
            items.append((self._store.read_attachment(attachment_id=attachment_id, content_hash=content_hash), observation))
        batch = self._batch.execute(items=tuple(items))
        ordinals: dict[str, int] = {}
        intents = []
        for asset in batch.assets:
            parent = asset["parent_document_id"]
            ordinals[parent] = ordinals.get(parent, 0) + 1
            intents.append(MediaRelationIntent(ordinals[parent], parent, asset.get("media_id"), "drawio", "embeds_media", "unresolved_target", "drawio-state"))
        metadata_assets = tuple(_relation_media_asset(asset) for asset in batch.assets)
        metadata = MediaMaterializationResult(assets=metadata_assets, relation_intents=tuple(intents))
        return {"media_result": metadata, "media_assets": tuple(batch.assets), "assets": metadata_assets}


def _required(args: argparse.Namespace, name: str) -> str:
    value = getattr(args, name, None)
    if type(value) is not str or not value:
        raise _ConfigurationError
    return value


def _build_operator_inputs(args: argparse.Namespace) -> tuple[M10SnapshotRequest, object, object]:
    """Construct the offline replay boundary from validated operator paths."""
    run_id = CrawlRunId(_required(args, "run_id"))
    generation_id = CrawlRunId(_required(args, "generation_id"))
    raw_root = Path(_required(args, "raw_generation_root"))
    dataset_root = Path(_required(args, "dataset_root"))
    chunk_path = Path(_required(args, "chunking_profile"))
    jira_path = Path(_required(args, "jira_relation_profile"))
    assets = Path(_required(args, "tokenizer_assets_dir"))
    rows, drawio_assets = _harness_state(args, run_id)
    pages = tuple(row["page_id"] for row in rows)
    spaces = tuple(sorted(set(args.space_keys or ())))
    roots = tuple(sorted(set(args.root_page_ids or ())))
    if not pages or not spaces or not roots:
        raise _ConfigurationError
    chunking = load_chunking_profile(chunk_path)
    jira = load_jira_relation_profile(jira_path)
    embedding_text = TextNormalizationRules.normalize_text(chunk_path.read_text(encoding="utf-8"))
    jira_text = TextNormalizationRules.normalize_text(jira_path.read_text(encoding="utf-8"))
    bundle = OnePageExportProfileBundle(chunking, jira, embedding_text, jira_text)
    identity = M10ProfileIdentity(embedding_text, jira_text)
    if args.profile_identity is not None and args.profile_identity != identity.config_hash:
        raise _ConfigurationError
    request = M10SnapshotRequest(
        run_id=run_id, generation_id=generation_id,
        confluence_scope=M10ConfluenceScope("confluence", spaces, roots, tuple(sorted(set(pages)))),
        confluence_exclusions=tuple(M10ConfluenceExclusion(x, "exclude_page") for x in sorted(set(args.excluded_page_ids or ()))),
        ordered_page_ids=pages, raw_generation_id=(args.raw_generation_id or _required(args, "generation_id")),
        git_repository=_required(args, "git_repository"), git_branch=_required(args, "git_branch"),
        git_commit=_required(args, "git_commit"), media_policy=_media_policy(args.media_policy),
        profile_bundle=bundle, generated_at=_required(args, "generated_at"),
        dataset_root=dataset_root, export_mode=args.export_mode,
        profile_identity=identity, base_dataset_version=args.base_dataset_version,
    )
    tokenizer = BgeM3LocalTokenizer(profile=chunking, tokenizer_assets_dir=assets)
    validator = FoundationSchemaValidator()
    confluence = ConfluenceM10CompositionRoot.build(
        raw_page_store=ConfluenceRawPageGenerationStore(raw_root=raw_root), tokenizer=tokenizer,
        chunking_profile=chunking, raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
        relation_stage=MaterializeConfluenceMediaRelations(schema_validator=validator),
        media_stage=_ReplayMediaStage(raw_root=raw_root, assets=drawio_assets, generated_at=args.generated_at, validator=validator, enabled=args.media_policy != "disabled"),
        schema_validator=validator,
    )
    return request, confluence, _EmptyGitAdapter()


def run(*, request: object, confluence_adapter: object, git_adapter: object, validator: FoundationSchemaValidator | None = None, prior_snapshot_reader: object | None = None, delta_inventory: tuple[object, ...] = ()):
    """Run the injected offline boundary; useful for tests and embedding."""
    if type(request) is M10SnapshotRequest and request.export_mode == "delta":
        if prior_snapshot_reader is None or not delta_inventory:
            raise M10SnapshotExportFailure("invalid_request")
        exporter = M10DeltaSnapshotExporter(prior_snapshot_reader=prior_snapshot_reader, delta_inventory=tuple(delta_inventory), confluence_adapter=confluence_adapter, git_adapter=git_adapter, schema_validator=validator)
    else:
        if prior_snapshot_reader is not None or delta_inventory:
            raise M10SnapshotExportFailure("invalid_request")
        exporter = M10FullSnapshotExporter(confluence_adapter=confluence_adapter, git_adapter=git_adapter, schema_validator=validator)
    return exporter.execute(request)


def main(
    argv: Sequence[str] | None = None,
    *,
    request: object | None = None,
    confluence_adapter: object | None = None,
    git_adapter: object | None = None,
    validator: FoundationSchemaValidator | None = None,
) -> int:
    _silence_m3_loggers()
    try:
        # Embedded callers use the injected seam and must not inherit the
        # host process' argv (for example pytest's own flags).
        parse_argv = [] if argv is None and request is not None else argv
        parsed = _parse_args(parse_argv)
        _media_policy(parsed.media_policy)
        if request is None and confluence_adapter is None and git_adapter is None:
            if argv is not None and len(argv) == 0:
                raise M10SnapshotExportFailure("invalid_request")
            try:
                request, confluence_adapter, git_adapter = _build_operator_inputs(parsed)
            except _ConfigurationError:
                raise
            except (OSError, TypeError, ValueError):
                raise _ConfigurationError from None
            prior_reader = None
            inventory_entries: tuple[object, ...] = ()
            if request.export_mode == "delta":
                if not parsed.state_dir or request.base_dataset_version is None:
                    raise _ConfigurationError
                try:
                    store = DeltaInventoryArtifactStore(state_root=Path(parsed.state_dir) / "runs")
                    envelope = store.read(generation_id=request.generation_id)
                    expected_selection = selection_identity(tuple(CurrentSelectionPage(page_id) for page_id in request.ordered_page_ids))
                    expected_scope = scope_identity(DeltaInventoryScope(tuple(request.confluence_scope.include_root_page_ids), tuple(item.page_id for item in request.confluence_exclusions), tuple(parsed.excluded_ancestor_page_ids or ())))
                    if (envelope.run_id != request.run_id or envelope.generation_id != request.generation_id or envelope.accepted_base_dataset_version != request.base_dataset_version or envelope.current_selection_identity != expected_selection or envelope.current_scope_identity != expected_scope):
                        raise ValueError
                    prior_reader = PublishedSnapshotReader(dataset_root=request.dataset_root, validator=validator or FoundationSchemaValidator())
                    inventory_entries = tuple(envelope.entries)
                except Exception:
                    raise _ConfigurationError from None
            else:
                prior_reader = None
                inventory_entries = ()
        elif request is None or confluence_adapter is None or git_adapter is None:
            raise M10SnapshotExportFailure("invalid_request")
        else:
            prior_reader = None
            inventory_entries = ()
        result = run(request=request, confluence_adapter=confluence_adapter, git_adapter=git_adapter, validator=validator, prior_snapshot_reader=prior_reader, delta_inventory=inventory_entries)
    except SystemExit as exc:
        if type(exc.code) is int:
            return exc.code
        return _fail("unexpected", EXIT_UNEXPECTED)
    except _ConfigurationError:
        return _fail("configuration", EXIT_CONFIGURATION)
    except M10CompositionRootError:
        return _fail("configuration", EXIT_CONFIGURATION)
    except M10SnapshotExportFailure as exc:
        return _fail(exc.category, _EXIT_CODES[exc.category])
    except BaseException:
        return _fail("unexpected", EXIT_UNEXPECTED)
    # Do not let a malformed injected result escape through this operator
    # boundary; only a published, runtime-validated result is printable.
    try:
        if type(result) is not M10SnapshotResult:
            raise TypeError
        M10SnapshotResult.__post_init__(result)
        if result.status != "published" or result.metrics is None:
            raise ValueError
        counts = {
            key: getattr(result.metrics, key)
            for key in ("documents", "chunks", "relations", "acl", "media_assets", "symbols", "sync_state", "tombstones")
        }
        payload = {
            "status": "success",
            "dataset_version": result.dataset_version,
            "digest": result.digest,
            "counts": counts,
            "network_used": False,
            "credentials_used": False,
        }
        sys.stdout.write(json.dumps(payload, sort_keys=True, allow_nan=False) + "\n")
    except BaseException:
        return _fail("unexpected", EXIT_UNEXPECTED)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
