"""CLI for the bounded Confluence subtree corpus harness."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path

from knowledgenexus.foundation.application.use_cases.confluence_subtree_corpus import (
    ConfluenceSubtreeCorpusConfig,
    SubtreePacketExporter,
    DrawioReference,
    capture_drawio_with_production_components,
    validate_drawio_capture_state,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId, InventoryRootCommit
from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import InventoryOccurrence
from knowledgenexus.foundation.domain.models.confluence_page_set import ConfluencePageSetResult, ConfluencePageWorkItem
from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import (
    CheckpointRunInventoryComplete,
    CheckpointRunSelectionFailure,
    CheckpointRunSelectionFailureCategory,
)
from knowledgenexus.foundation.ports.path_safety import require_plain_directory_chain, require_plain_file


_SELECTION_FORMAT = "confluence-subtree-selection-v1"
_ACTIVATION_FAILURE_CATEGORIES = {
    CheckpointRunSelectionFailureCategory.RUN_OPERATION_INVALID:
        "raw_generation_activation_run_operation_invalid",
    CheckpointRunSelectionFailureCategory.RUN_NOT_FOUND:
        "raw_generation_activation_run_not_found",
    CheckpointRunSelectionFailureCategory.RUN_NOT_RESUMABLE:
        "raw_generation_activation_run_not_resumable",
    CheckpointRunSelectionFailureCategory.RUN_MATCH_AMBIGUOUS:
        "raw_generation_activation_run_match_ambiguous",
    CheckpointRunSelectionFailureCategory.INCOMPLETE_RUN_CONFLICT:
        "raw_generation_activation_incomplete_run_conflict",
}
_PROCESSING_FORMAT = "confluence-subtree-processing-state-v1"
_STATE_NAMES = frozenset({"inventory-selection.json", "processing-state.json", "drawio-state.json", "delta-inventory.json"})
_MAX_STATE_BYTES = 64 * 1024 * 1024
_SELECTION_FIELDS = frozenset({"format_version", "run_id", "generation_id", "selection_identity", "items"})
_PROCESSING_FIELDS = frozenset({
    "format_version", "run_id", "generation_id", "selection_identity",
    "page_count", "completed_pages", "failed_pages", "drawio_references",
})
_RAW_ATTACHMENT_URI = re.compile(r"raw://confluence/attachments/(?P<attachment_id>[^/]+)/(?P<content_hash>[0-9a-f]{64})")


def _reject_duplicate_keys(pairs: list[tuple[object, object]]) -> dict[object, object]:
    output: dict[object, object] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("state contains duplicate keys")
        output[key] = value
    return output


def _read_json(path: Path) -> object:
    if not path.is_absolute():
        raise ValueError("state path is invalid")
    require_plain_directory_chain(path.parent)
    require_plain_file(path)
    if path.stat().st_size > _MAX_STATE_BYTES:
        raise ValueError("state artifact is too large")
    try:
        return json.loads(
            path.read_bytes().decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("invalid JSON constant")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
        raise ValueError("state artifact is invalid") from None


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _selection_identity(rows: list[dict[str, object]]) -> str:
    return hashlib.sha256(_canonical_json_bytes(rows)).hexdigest()


def _require_run_id(value: object) -> CrawlRunId:
    if type(value) is CrawlRunId:
        try:
            return CrawlRunId(value.value)
        except Exception:
            raise ValueError("run id is invalid") from None
    if type(value) is str:
        try:
            return CrawlRunId(value)
        except Exception:
            raise ValueError("run id is invalid") from None
    raise TypeError("run id is invalid")


def _load_subtree_selection(path: Path, max_pages: int, *, expected_run_id: CrawlRunId | None = None) -> tuple[ConfluencePageWorkItem, ...]:
    if not path.is_absolute() or type(max_pages) is not int or max_pages <= 0 or max_pages > 5000:
        raise ValueError("invalid selection")
    payload = _read_json(path)
    if type(payload) is dict:
        if frozenset(payload) != _SELECTION_FIELDS or payload.get("format_version") != _SELECTION_FORMAT:
            raise ValueError("invalid selection")
        run_id = _require_run_id(payload.get("run_id"))
        if payload.get("generation_id") != str(run_id) or (expected_run_id is not None and run_id != expected_run_id):
            raise ValueError("selection binding mismatch")
        rows = payload.get("items")
        if type(rows) is not list or payload.get("selection_identity") != _selection_identity(rows):
            raise ValueError("selection binding mismatch")
        payload = rows
    if type(payload) is not list or not payload or len(payload) > max_pages or len(payload) > 5000:
        raise ValueError("invalid selection")
    items = tuple(ConfluencePageWorkItem(page_id=x["page_id"], crawled_at=x["crawled_at"], expected_source_version=x.get("expected_source_version")) for x in payload if type(x) is dict)
    if (
        len(items) != len(payload)
        or len({item.page_id for item in items}) != len(items)
        or any(item.expected_source_version is None for item in items)
    ):
        raise ValueError("invalid selection")
    return items


def _atomic_json(path: Path, payload: object, *, replace: bool = False) -> None:
    if not path.is_absolute():
        raise ValueError("state path is invalid")
    require_plain_directory_chain(path.parent)
    content = _canonical_json_bytes(payload)
    if path.exists():
        require_plain_file(path)
        if not replace:
            if path.read_bytes() != content:
                raise ValueError("state replay conflict")
            return
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        raise ValueError("state temporary artifact already exists")
    try:
        with tmp.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        require_plain_file(tmp)
        if replace:
            os.replace(tmp, path)
        else:
            os.link(tmp, path)
            tmp.unlink()
    finally:
        if tmp.exists():
            tmp.unlink()

def _state_path(state: Path, run_id: str, name: str) -> Path:
    run = _require_run_id(run_id)
    if name not in _STATE_NAMES:
        raise ValueError("state artifact name is invalid")
    if not state.is_absolute():
        raise ValueError("state path is invalid")
    if state.exists():
        require_plain_directory_chain(state)
    else:
        require_plain_directory_chain(state.parent)
        state.mkdir()
    runs = state / "runs"
    if runs.exists():
        require_plain_directory_chain(runs)
    else:
        runs.mkdir()
    root = runs / str(run)
    if root.exists():
        require_plain_directory_chain(root)
    else:
        root.mkdir()
    require_plain_directory_chain(root)
    return root / name


def _assert_root_page_in_selection(root_page_id: str, selection: Mapping[str, object]) -> None:
    """Fail closed if the published selection ever drops the configured root.

    A COMPLETE inventory phase implies the root was durably committed, but
    nothing else in this module cross-checks the operator's configured
    ``--root-page-id`` against what actually got published.
    """
    rows = selection.get("items")
    if type(rows) is not list or not any(
        type(row) is dict and row.get("page_id") == root_page_id for row in rows
    ):
        raise ValueError("published selection is missing the configured root page")


def _selection_payload_from_inventory(
    *,
    run_id: CrawlRunId,
    facts: Iterable[InventoryRootCommit | InventoryOccurrence],
    max_pages: int,
    crawled_at: str,
) -> dict[str, object]:
    ordered: list[tuple[str, str | None]] = []
    seen: dict[str, str | None] = {}
    for fact in facts:
        if type(fact) not in (InventoryRootCommit, InventoryOccurrence) or fact.run_id != run_id:
            raise ValueError("inventory fact is invalid")
        page_id = fact.metadata.page_id
        version = fact.metadata.source_version
        if version is None:
            raise ValueError("inventory page version missing")
        if page_id in seen:
            if seen[page_id] != version:
                raise ValueError("inventory page version conflict")
            continue
        seen[page_id] = version
        ordered.append((page_id, version))
    if not ordered or len(ordered) > max_pages:
        raise ValueError("inventory exceeds bound")
    rows = [
        {"page_id": page_id, "crawled_at": crawled_at, "expected_source_version": version}
        for page_id, version in ordered
    ]
    # Rebuild through the active page-set model before publication.
    tuple(ConfluencePageWorkItem(**row) for row in rows)
    return {
        "format_version": _SELECTION_FORMAT,
        "run_id": str(run_id),
        "generation_id": str(run_id),
        "selection_identity": _selection_identity(rows),
        "items": rows,
    }


def _load_selection_payload(path: Path, *, run_id: CrawlRunId, max_pages: int) -> tuple[dict[str, object], tuple[ConfluencePageWorkItem, ...]]:
    payload = _read_json(path)
    if type(payload) is not dict:
        raise ValueError("selection envelope is invalid")
    items = _load_subtree_selection(path, max_pages, expected_run_id=run_id)
    return dict(payload), items


def _processing_payload(
    *,
    run_id: CrawlRunId,
    selection: Mapping[str, object],
    result: ConfluencePageSetResult,
) -> dict[str, object]:
    if type(result) is not ConfluencePageSetResult:
        raise TypeError("page processing result is invalid")
    selection_identity = selection.get("selection_identity")
    rows = selection.get("items")
    if type(selection_identity) is not str or type(rows) is not list:
        raise ValueError("selection envelope is invalid")
    selected_versions = {
        row["page_id"]: row.get("expected_source_version")
        for row in rows
        if type(row) is dict and type(row.get("page_id")) is str
    }
    if len(selected_versions) != len(rows):
        raise ValueError("selection envelope is invalid")
    documents = {record.get("document_id"): record for record in result.documents}
    references: dict[tuple[str, str, str], DrawioReference] = {}
    for document_id, intents in result.reference_intents_by_page:
        document = documents.get(document_id)
        if type(document) is not dict:
            raise ValueError("reference document binding is invalid")
        page_id = document.get("page_id")
        source_version = document.get("source_version")
        if (
            type(page_id) is not str
            or page_id not in selected_versions
            or type(source_version) is not str
            or source_version != selected_versions[page_id]
        ):
            raise ValueError("reference source binding is invalid")
        for intent in intents:
            if intent.kind == "drawio":
                reference = DrawioReference(page_id, intent.target_identity, source_version)
                key = (reference.parent_page_id, reference.filename, reference.parent_source_version)
                references[key] = reference
    metrics = result.metrics
    if metrics.requested_pages != len(rows) or metrics.succeeded_pages + metrics.failed_pages != len(rows):
        raise ValueError("page processing counts are invalid")
    refs = [
        {
            "parent_page_id": ref.parent_page_id,
            "filename": ref.filename,
            "parent_source_version": ref.parent_source_version,
        }
        for ref in (references[key] for key in sorted(references))
    ]
    return {
        "format_version": _PROCESSING_FORMAT,
        "run_id": str(run_id),
        "generation_id": str(run_id),
        "selection_identity": selection_identity,
        "page_count": len(rows),
        "completed_pages": metrics.succeeded_pages,
        "failed_pages": metrics.failed_pages,
        "drawio_references": refs,
    }


def _load_processing_payload(path: Path, *, run_id: CrawlRunId, selection_identity: str) -> dict[str, object]:
    payload = _read_json(path)
    if type(payload) is not dict or frozenset(payload) != _PROCESSING_FIELDS:
        raise ValueError("processing state is invalid")
    if (
        payload.get("format_version") != _PROCESSING_FORMAT
        or payload.get("run_id") != str(run_id)
        or payload.get("generation_id") != str(run_id)
        or payload.get("selection_identity") != selection_identity
    ):
        raise ValueError("processing state binding mismatch")
    counts = (payload.get("page_count"), payload.get("completed_pages"), payload.get("failed_pages"))
    if any(type(value) is not int or value < 0 for value in counts) or counts[1] + counts[2] != counts[0]:
        raise ValueError("processing state counts are invalid")
    raw_refs = payload.get("drawio_references")
    if type(raw_refs) is not list:
        raise ValueError("processing references are invalid")
    refs = tuple(
        DrawioReference(item["parent_page_id"], item["filename"], item["parent_source_version"])
        for item in raw_refs
        if type(item) is dict and set(item) == {"parent_page_id", "filename", "parent_source_version"}
    )
    if len(refs) != len(raw_refs) or tuple(sorted(refs, key=lambda ref: (ref.parent_page_id, ref.filename, ref.parent_source_version))) != refs:
        raise ValueError("processing references are invalid")
    if len({(ref.parent_page_id, ref.filename, ref.parent_source_version) for ref in refs}) != len(refs):
        raise ValueError("processing references contain duplicates")
    return dict(payload)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="confluence-subtree-corpus")
    subparsers = parser.add_subparsers(dest="phase", required=True)
    for name in ("inventory", "capture-pages", "process-pages", "capture-drawio", "capture-delta-inventory", "export"):
        phase = subparsers.add_parser(name)
        phase.add_argument("--state-dir", required=True)
        phase.add_argument("--max-pages", type=int, required=True)
        phase.add_argument("--batch-size", type=int, default=100)
        phase.add_argument("--output-dir")
        phase.add_argument("--raw-root")
        phase.add_argument("--selection-path")
        phase.add_argument("--reliability-profile-path")
        phase.add_argument("--chunking-profile-path")
        phase.add_argument("--tokenizer-assets-dir")
        phase.add_argument("--run-id")
        phase.add_argument("--resume-run-id")
        phase.add_argument("--resume-unique", action="store_true")
        phase.add_argument("--space-key")
        phase.add_argument("--root-page-id")
        phase.add_argument("--include-root-page-id", action="append", dest="include_root_page_ids")
        phase.add_argument("--exclude-page-id", action="append", dest="excluded_page_ids")
        phase.add_argument("--exclude-ancestor-page-id", action="append", dest="excluded_ancestor_page_ids")
        phase.add_argument("--base-dataset-version")
        phase.add_argument("--dataset-root")
        if name == "capture-pages":
            phase.add_argument("--stop-after-batches", type=_positive_int)
    return parser


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("value must be a positive integer") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _load_reliability_profile(value: object) -> dict[str, object]:
    if type(value) is not str:
        raise ValueError("reliability profile is required")
    path = Path(value)
    payload = _read_yaml_mapping(path)
    from knowledgenexus.foundation.infrastructure.confluence.confluence_retrying_http_transport import ConfluenceRetryExecutorProfile
    ConfluenceRetryExecutorProfile.from_mapping(payload)
    return payload


def _read_yaml_mapping(path: Path) -> dict[str, object]:
    if not path.is_absolute():
        raise ValueError("profile path must be absolute")
    require_plain_directory_chain(path.parent)
    require_plain_file(path)
    try:
        import yaml
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        raise ValueError("profile is invalid") from None
    if type(payload) is not dict or any(type(key) is not str for key in payload):
        raise ValueError("profile is invalid")
    return dict(payload)


def _source_config(args: argparse.Namespace, profile: Mapping[str, object]):
    if not args.space_key or not args.root_page_id:
        raise ValueError("Confluence scope is required")
    from knowledgenexus.foundation.domain.models.confluence_source_config import ConfluenceIncludeRoot, ConfluenceSourceConfig
    return ConfluenceSourceConfig(
        source_id="confluence-root1",
        space_key=args.space_key,
        include_roots=(ConfluenceIncludeRoot(page_id=args.root_page_id),),
        page_size=profile["inventory_page_size"],
    )


def _corpus_config(args: argparse.Namespace, profile: Mapping[str, object]) -> ConfluenceSubtreeCorpusConfig:
    if args.max_pages > profile["max_pages_per_run"]:
        raise ValueError("page bound exceeds reliability profile")
    return ConfluenceSubtreeCorpusConfig(
        max_pages=args.max_pages,
        batch_size=args.batch_size,
        inventory_window=profile["inventory_page_size"],
        request_budget=profile["max_total_requests_per_run"],
        retry_budget=profile["max_attempts"],
        page_bytes=profile["max_response_bytes_per_request"],
        total_bytes=profile["max_raw_bytes_per_run"],
        drawio_count=profile["max_raw_artifacts_per_run"],
        drawio_bytes=profile["max_raw_bytes_per_run"],
        free_disk_bytes=profile["minimum_free_disk_reserve_bytes"],
    )


def _validated_page_bound(
    args: argparse.Namespace, profile: Mapping[str, object]
) -> Mapping[str, object]:
    """Reject an operator page cap that exceeds the approved reliability profile.

    The reliability profile is a closed, fingerprinted contract: only its
    approved values may reach the checkpoint registry or live composition
    (``_validate_profile`` rejects anything else). The operator's smaller
    ``--max-pages`` is therefore enforced separately, by
    ``ConfluenceSubtreeCorpusConfig`` and by the inventory-selection bound,
    against this unmodified profile -- it must never be written back into
    the profile mapping itself.
    """
    if type(args.max_pages) is not int or args.max_pages <= 0:
        raise ValueError("page bound is invalid")
    configured = profile.get("max_pages_per_run")
    if type(configured) is not int or args.max_pages > configured:
        raise ValueError("page bound exceeds reliability profile")
    return profile


def _drawio_config(
    args: argparse.Namespace,
    profile: Mapping[str, object],
    base_config: ConfluenceSubtreeCorpusConfig,
    run_id: CrawlRunId,
    items: tuple[ConfluencePageWorkItem, ...],
    *,
    required_count: int,
) -> ConfluenceSubtreeCorpusConfig:
    if type(required_count) is not int or required_count < 0:
        raise ValueError("Draw.io reference count is invalid")
    remaining_artifacts = profile["max_raw_artifacts_per_run"] - len(items)
    remaining_bytes = profile["max_raw_bytes_per_run"] - _raw_page_bytes(
        args, run_id, items
    )
    if (
        remaining_artifacts < required_count
        or remaining_bytes < 0
        or (required_count > 0 and remaining_bytes == 0)
    ):
        raise ValueError("raw generation budget exhausted")
    return ConfluenceSubtreeCorpusConfig(
        max_pages=base_config.max_pages,
        batch_size=base_config.batch_size,
        inventory_window=base_config.inventory_window,
        request_budget=base_config.request_budget,
        retry_budget=base_config.retry_budget,
        page_bytes=base_config.page_bytes,
        total_bytes=base_config.total_bytes,
        drawio_count=max(1, remaining_artifacts),
        drawio_bytes=max(1, remaining_bytes),
        free_disk_bytes=base_config.free_disk_bytes,
    )


def _selection_file(args: argparse.Namespace, state: Path, run_id: CrawlRunId) -> Path:
    return Path(args.selection_path) if args.selection_path else _state_path(state, str(run_id), "inventory-selection.json")


def _activation_failure(outcome: object) -> dict[str, object] | None:
    if isinstance(outcome, CheckpointRunSelectionFailure):
        category = _ACTIVATION_FAILURE_CATEGORIES.get(outcome.category)
        if category is None:
            category = "raw_generation_activation_run_operation_invalid"
        return {"status": "failed", "failure_category": category}
    if isinstance(outcome, CheckpointRunInventoryComplete):
        return {
            "status": "failed",
            "failure_category": "raw_generation_activation_run_operation_invalid",
        }
    return None


def _activation_methods(outcome: object):
    try:
        stream = getattr(outcome, "stream_inventory_occurrences")
        pause = getattr(outcome, "pause_session")
    except Exception:
        return None
    if not callable(stream) or not callable(pause):
        return None
    return stream, pause


def _compose_page_processor(args: argparse.Namespace, *, run_id: CrawlRunId, items: tuple[ConfluencePageWorkItem, ...]):
    if not args.raw_root or not args.chunking_profile_path or not args.tokenizer_assets_dir:
        raise ValueError("page processing inputs are required")
    from knowledgenexus.foundation.application.use_cases.process_confluence_page_set import ProcessConfluencePageSet
    from knowledgenexus.foundation.domain.models.confluence_page_set import ACTIVE_PAGE_SET_PROFILE_IDENTITY, ConfluencePageSetRequest
    from knowledgenexus.foundation.infrastructure.config.chunking_profile_loader import load_chunking_profile
    from knowledgenexus.foundation.infrastructure.processors import ConfluenceDataCenterRawPageMapper, ConfluenceStorageXhtmlNormalizer
    from knowledgenexus.foundation.infrastructure.raw_store import ConfluenceRawPageGenerationStore
    from knowledgenexus.foundation.infrastructure.tokenization import BgeM3LocalTokenizer
    profile = load_chunking_profile(Path(args.chunking_profile_path))
    request = ConfluencePageSetRequest(run_id=run_id, generation_id=run_id, items=items, profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY)
    return ProcessConfluencePageSet(
        chunking_profile=profile,
        tokenizer=BgeM3LocalTokenizer(profile=profile, tokenizer_assets_dir=Path(args.tokenizer_assets_dir)),
        raw_page_store=ConfluenceRawPageGenerationStore(raw_root=Path(args.raw_root)),
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
        schema_validator=FoundationSchemaValidator(),
    ).execute(request=request)


def _inventory_phase(args: argparse.Namespace, state: Path) -> dict[str, object]:
    if not args.raw_root:
        raise ValueError("raw root is required")
    profile = _validated_page_bound(
        args, _load_reliability_profile(args.reliability_profile_path)
    )
    _corpus_config(args, profile)
    source_config = _source_config(args, profile)
    from knowledgenexus.foundation.infrastructure.confluence import compose_live_subtree
    from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import (
        ActivateRawGenerationRequest, ResumeExplicitRunRequest,
        ResumeUniqueIncompleteRunRequest, StartNewRunRequest,
    )
    composition = compose_live_subtree(
        raw_root=Path(args.raw_root), checkpoint_workspace=state,
        reliability_profile=profile, max_search_pages=profile["max_inventory_windows_per_root"],
    )
    common = dict(workspace=state, endpoint_url=os.environ.get("CONFLUENCE_BASE_URL", ""), source_config=source_config, reliability_profile=profile)
    if args.resume_run_id:
        request = ResumeExplicitRunRequest(run_id=_require_run_id(args.resume_run_id), **common)
    elif args.resume_unique:
        request = ResumeUniqueIncompleteRunRequest(**common)
    else:
        request = StartNewRunRequest(**common)
    result = composition.inventory_use_case(max_search_pages=profile["max_inventory_windows_per_root"]).execute(request=request)
    snapshot = result.snapshot
    if snapshot is None:
        raise ValueError("inventory snapshot missing")
    if snapshot.inventory_phase.value != "complete":
        return {"status": result.status, "phase": "inventory", "selected_pages": 0}
    activation_request = ActivateRawGenerationRequest(run_id=snapshot.run_id, **common)
    activation_failure = None
    stream_failed = False
    facts = None
    with composition.checkpoint_run_port.activate_raw_generation(activation_request) as session:
        activation_failure = _activation_failure(session)
        if activation_failure is None:
            methods = _activation_methods(session)
            if methods is None:
                activation_failure = {
                    "status": "failed",
                    "failure_category": "raw_generation_activation_run_operation_invalid",
                }
            else:
                stream, pause = methods
                try:
                    # Read at most one item beyond the operator's page cap.
                    facts = tuple(
                        islice(
                            stream(batch_size=args.batch_size),
                            args.max_pages + 1,
                        )
                    )
                except Exception:
                    stream_failed = True
                finally:
                    pause()
    if activation_failure is not None:
        return activation_failure
    if stream_failed:
        return {"status": "failed", "failure_category": "inventory_stream"}
    if facts is None:
        return {
            "status": "failed",
            "failure_category": "raw_generation_activation_run_operation_invalid",
        }
    try:
        selection_path = _state_path(
            state, str(snapshot.run_id), "inventory-selection.json"
        )
    except (OSError, TypeError, ValueError):
        return {"status": "failed", "failure_category": "selection_publication"}

    if selection_path.exists():
        try:
            existing, existing_items = _load_selection_payload(
                selection_path,
                run_id=snapshot.run_id,
                max_pages=args.max_pages,
            )
            candidate = _selection_payload_from_inventory(
                run_id=snapshot.run_id,
                facts=facts,
                max_pages=args.max_pages,
                crawled_at=existing_items[0].crawled_at,
            )
            if candidate != existing:
                raise ValueError("selection replay conflict")
            selection = existing
            _assert_root_page_in_selection(args.root_page_id, selection)
        except OSError:
            return {
                "status": "failed",
                "failure_category": "selection_publication",
            }
        except (TypeError, ValueError):
            return {
                "status": "failed",
                "failure_category": "inventory_selection_invalid",
            }
    else:
        try:
            crawled_at = (
                datetime.now(timezone.utc)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z")
            )
            selection = _selection_payload_from_inventory(
                run_id=snapshot.run_id,
                facts=facts,
                max_pages=args.max_pages,
                crawled_at=crawled_at,
            )
            _assert_root_page_in_selection(args.root_page_id, selection)
        except (TypeError, ValueError):
            return {
                "status": "failed",
                "failure_category": "inventory_selection_invalid",
            }
        try:
            _atomic_json(selection_path, selection)
        except (OSError, TypeError, ValueError):
            return {
                "status": "failed",
                "failure_category": "selection_publication",
            }
    return {"status": "complete", "phase": "inventory", "selected_pages": len(selection["items"]), "run_id": str(snapshot.run_id)}


def _capture_pages_phase(args: argparse.Namespace, state: Path) -> dict[str, object]:
    if not args.raw_root or not args.run_id:
        raise ValueError("live page capture inputs are required")
    run_id = _require_run_id(args.run_id)
    profile = _validated_page_bound(
        args, _load_reliability_profile(args.reliability_profile_path)
    )
    config = _corpus_config(args, profile)
    source_config = _source_config(args, profile)
    selection_path = _selection_file(args, state, run_id)
    selection_payload, selection_items = _load_selection_payload(selection_path, run_id=run_id, max_pages=args.max_pages)
    from knowledgenexus.foundation.infrastructure.confluence import compose_live_subtree
    from knowledgenexus.foundation.application.use_cases.capture_confluence_subtree_pages import CaptureConfluenceSubtreePages
    from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_page_orphan_inspector import ConfluenceRawPageOrphanInspector
    from knowledgenexus.foundation.infrastructure.confluence.confluence_retrying_http_transport import RetryingConfluenceHttpTransport
    from knowledgenexus.foundation.infrastructure.confluence.confluence_data_center_page_adapter import ConfluenceDataCenterPageAdapter
    from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import ActivateRawGenerationRequest
    composition = compose_live_subtree(raw_root=Path(args.raw_root), checkpoint_workspace=state, reliability_profile=profile, max_search_pages=profile["max_inventory_windows_per_root"])
    request = ActivateRawGenerationRequest(workspace=state, run_id=run_id, endpoint_url=os.environ.get("CONFLUENCE_BASE_URL", ""), source_config=source_config, reliability_profile=profile)
    activation_failure = None
    stream_failed = False
    captured = None
    with composition.checkpoint_run_port.activate_raw_generation(request) as session:
        activation_failure = _activation_failure(session)
        if activation_failure is None:
            methods = _activation_methods(session)
            if methods is None:
                activation_failure = {
                    "status": "failed",
                    "failure_category": "raw_generation_activation_run_operation_invalid",
                }
            else:
                stream, pause = methods
                try:
                    facts = tuple(
                        islice(
                            stream(batch_size=args.batch_size),
                            args.max_pages + 1,
                        )
                    )
                except Exception:
                    stream_failed = True
                    pause()
                else:
                    try:
                        candidate = _selection_payload_from_inventory(run_id=run_id, facts=facts, max_pages=args.max_pages, crawled_at=selection_items[0].crawled_at)
                        if candidate != selection_payload:
                            raise ValueError("selection binding mismatch")
                        transport = RetryingConfluenceHttpTransport(inner=composition.http_inner, profile=composition.retry_profile, monotonic_clock=time.monotonic, sleeper=time.sleep, attempt_reserver=session)
                        use_case = CaptureConfluenceSubtreePages(
                            state_session=session,
                            orphan_inspector=ConfluenceRawPageOrphanInspector(raw_root=Path(args.raw_root)),
                            page_fetcher=ConfluenceDataCenterPageAdapter(transport=transport),
                            raw_page_store=composition.guarded_raw_page_store(activation=session),
                            max_pages=config.max_pages,
                        )
                        captured = use_case.run(
                            run_id=run_id,
                            occurrences=facts,
                            stop_after_batches=getattr(args, "stop_after_batches", None),
                        )
                    except Exception:
                        try:
                            pause()
                        except Exception:
                            pass
                        raise
                    if captured.complete:
                        session.complete_session()
                    else:
                        pause()
    if activation_failure is not None:
        return activation_failure
    if stream_failed:
        return {"status": "failed", "failure_category": "inventory_stream"}
    if captured is None:
        return {
            "status": "failed",
            "failure_category": "raw_generation_activation_run_operation_invalid",
        }
    return _capture_pages_result_payload(captured)


def _capture_pages_result_payload(captured: object) -> dict[str, object]:
    from knowledgenexus.foundation.application.use_cases.capture_confluence_subtree_pages import PageCaptureResult

    if type(captured) is not PageCaptureResult:
        raise TypeError("capture result is invalid")
    result: dict[str, object] = {
        "status": "complete" if captured.complete else "stopped",
        "phase": "capture-pages", "captured": captured.captured,
        "replayed": captured.replayed, "skipped": captured.skipped,
        "failed": captured.failed,
    }
    if captured.failure_categories:
        result["failure_categories"] = dict(captured.failure_categories)
    return result


def _process_pages_phase(args: argparse.Namespace, state: Path) -> dict[str, object]:
    if not args.run_id:
        raise ValueError("run id is required")
    run_id = _require_run_id(args.run_id)
    selection, items = _load_selection_payload(_selection_file(args, state, run_id), run_id=run_id, max_pages=args.max_pages)
    processed = _compose_page_processor(args, run_id=run_id, items=items)
    processing = _processing_payload(run_id=run_id, selection=selection, result=processed)
    if processing["failed_pages"] != 0 or not processed.documents or not processed.chunks:
        raise ValueError("page processing incomplete")
    _atomic_json(_state_path(state, str(run_id), "processing-state.json"), processing)
    return {"status": "complete", "phase": "process-pages", "page_count": len(items), "document_count": len(processed.documents), "chunk_count": len(processed.chunks)}


def _raw_page_bytes(args: argparse.Namespace, run_id: CrawlRunId, items: tuple[ConfluencePageWorkItem, ...]) -> int:
    from knowledgenexus.foundation.infrastructure.raw_store import ConfluenceRawPageGenerationStore
    store = ConfluenceRawPageGenerationStore(raw_root=Path(args.raw_root))
    total = 0
    for item in items:
        path = store.resolve_page_path(run_id=run_id, page_id=item.page_id)
        require_plain_file(path)
        total += path.stat().st_size
    return total


def _capture_drawio_phase(args: argparse.Namespace, state: Path) -> dict[str, object]:
    if not args.run_id or not args.raw_root:
        raise ValueError("Draw.io capture inputs are required")
    run_id = _require_run_id(args.run_id)
    profile = _validated_page_bound(
        args, _load_reliability_profile(args.reliability_profile_path)
    )
    base_config = _corpus_config(args, profile)
    source_config = _source_config(args, profile)
    selection, items = _load_selection_payload(_selection_file(args, state, run_id), run_id=run_id, max_pages=args.max_pages)
    processing_path = _state_path(state, str(run_id), "processing-state.json")
    processing = _load_processing_payload(processing_path, run_id=run_id, selection_identity=selection["selection_identity"])
    if processing["failed_pages"] != 0 or processing["page_count"] != len(items):
        raise ValueError("page processing incomplete")
    refs = tuple(DrawioReference(item["parent_page_id"], item["filename"], item["parent_source_version"]) for item in processing["drawio_references"])
    config = _drawio_config(
        args, profile, base_config, run_id, items, required_count=len(refs)
    )
    state_path = _state_path(state, str(run_id), "drawio-state.json")
    prior = _read_json(state_path) if state_path.exists() else None
    persist = lambda payload: _atomic_json(state_path, payload, replace=True)
    if not refs:
        captured = capture_drawio_with_production_components(
            references=(), attachment_observer=None, body_materializer=None,
            media_processor=None, run_id=run_id,
            selection_identity=selection["selection_identity"], prior_state=prior,
            persist_state=persist, config=config,
        )
    else:
        from knowledgenexus.foundation.infrastructure.confluence import compose_live_subtree
        from knowledgenexus.foundation.infrastructure.confluence.confluence_retrying_http_transport import RetryingConfluenceHttpTransport
        from knowledgenexus.foundation.domain.models.media_body_materialization import MediaBodyStoreBudget
        from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import ActivateRawGenerationRequest
        composition = compose_live_subtree(raw_root=Path(args.raw_root), checkpoint_workspace=state, reliability_profile=profile, max_search_pages=profile["max_inventory_windows_per_root"])
        request = ActivateRawGenerationRequest(workspace=state, run_id=run_id, endpoint_url=os.environ.get("CONFLUENCE_BASE_URL", ""), source_config=source_config, reliability_profile=profile)
        attachment_root = Path(args.raw_root) / "attachments"
        if attachment_root.exists():
            require_plain_directory_chain(attachment_root)
        else:
            require_plain_directory_chain(attachment_root.parent)
            attachment_root.mkdir()
        with composition.checkpoint_run_port.activate_raw_generation(request) as session:
            transport = RetryingConfluenceHttpTransport(inner=composition.http_inner, profile=composition.retry_profile, monotonic_clock=time.monotonic, sleeper=time.sleep, attempt_reserver=session)
            max_body = min(profile["max_response_bytes_per_request"], config.drawio_bytes)
            budget = MediaBodyStoreBudget(max_body_bytes=max_body, max_total_bytes=config.drawio_bytes, minimum_free_disk_reserve_bytes=profile["minimum_free_disk_reserve_bytes"])
            observer, materializer, processor = composition.attachment_components(
                attachment_root=attachment_root, budget=budget,
                attachment_page_size=profile["attachment_page_size"],
                max_attachment_pages=profile["max_attachment_windows_per_page"],
                transport=transport,
            )
            captured = capture_drawio_with_production_components(
                references=refs, attachment_observer=observer,
                body_materializer=materializer, media_processor=processor,
                run_id=run_id, selection_identity=selection["selection_identity"],
                prior_state=prior, persist_state=persist, config=config,
            )
            if captured["drawio_assets_failed"] == 0 and captured["drawio_references_resolved"] == captured["drawio_references_observed"]:
                session.complete_session()
            else:
                session.pause_session()
    if captured["drawio_assets_failed"] != 0 or captured["drawio_references_resolved"] != captured["drawio_references_observed"]:
        # Naming the counts distinguishes "some downloads failed" from "some
        # references were never even observed" -- two different problems that
        # both used to read as the same four words.
        raise ValueError(
            "Draw.io capture incomplete: "
            f"observed={captured['drawio_references_observed']} "
            f"resolved={captured['drawio_references_resolved']} "
            f"failed={captured['drawio_assets_failed']}"
        )
    return {"status": "complete", "phase": "capture-drawio", "drawio_references_observed": captured["drawio_references_observed"], "drawio_references_resolved": captured["drawio_references_resolved"], "drawio_assets_failed": captured["drawio_assets_failed"]}


def _verify_drawio_media_assets_on_disk(
    *,
    raw_root: Path,
    media_assets: list[dict[str, object]],
    profile: Mapping[str, object],
    drawio_config: ConfluenceSubtreeCorpusConfig,
) -> None:
    """Re-read every Draw.io raw attachment body from disk before publication.

    ``drawio-state.json`` only proves its own resolutions are internally
    consistent; it does not prove the referenced raw evidence still exists
    unmodified. A deleted or truncated artifact must fail export closed
    instead of publishing a packet that claims zero Draw.io failures.
    """
    if not media_assets:
        return
    from knowledgenexus.foundation.domain.models.media_body_materialization import MediaBodyStoreBudget
    from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_attachment_store import (
        ConfluenceRawAttachmentStore,
    )
    from knowledgenexus.foundation.ports.confluence_raw_attachment_store_port import (
        ConfluenceRawAttachmentStoreError,
    )
    max_body = min(profile["max_response_bytes_per_request"], drawio_config.drawio_bytes)
    budget = MediaBodyStoreBudget(
        max_body_bytes=max_body, max_total_bytes=drawio_config.drawio_bytes,
        minimum_free_disk_reserve_bytes=profile["minimum_free_disk_reserve_bytes"],
    )
    store = ConfluenceRawAttachmentStore(data_root=raw_root / "attachments", budget=budget)
    for asset in media_assets:
        raw_uri = asset.get("raw_uri")
        content_hash = asset.get("content_hash")
        size_bytes = asset.get("size_bytes")
        if type(raw_uri) is not str or type(content_hash) is not str or type(size_bytes) is not int:
            raise ValueError("drawio media asset raw evidence is invalid")
        match = _RAW_ATTACHMENT_URI.fullmatch(raw_uri)
        if match is None or match.group("content_hash") != content_hash:
            raise ValueError("drawio media asset raw evidence is invalid")
        try:
            envelope = store.read_attachment(
                attachment_id=match.group("attachment_id"), content_hash=content_hash,
            )
        except ConfluenceRawAttachmentStoreError:
            raise ValueError("drawio media asset raw evidence is missing or modified") from None
        if len(envelope.body_bytes) != size_bytes:
            raise ValueError("drawio media asset raw evidence is missing or modified")


def _export_phase(args: argparse.Namespace, state: Path) -> dict[str, object]:
    if not args.run_id or not args.output_dir or not args.raw_root:
        raise ValueError("export inputs are required")
    run_id = _require_run_id(args.run_id)
    reliability = _validated_page_bound(
        args, _load_reliability_profile(args.reliability_profile_path)
    )
    config = _corpus_config(args, reliability)
    selection, items = _load_selection_payload(_selection_file(args, state, run_id), run_id=run_id, max_pages=args.max_pages)
    processed = _compose_page_processor(args, run_id=run_id, items=items)
    current_processing = _processing_payload(run_id=run_id, selection=selection, result=processed)
    recorded_processing = _load_processing_payload(_state_path(state, str(run_id), "processing-state.json"), run_id=run_id, selection_identity=selection["selection_identity"])
    if current_processing != recorded_processing or current_processing["failed_pages"] != 0:
        raise ValueError("processing state changed")
    refs = tuple(DrawioReference(item["parent_page_id"], item["filename"], item["parent_source_version"]) for item in current_processing["drawio_references"])
    observed_keys = tuple((ref.parent_page_id, ref.filename, ref.parent_source_version) for ref in refs)
    drawio_path = _state_path(state, str(run_id), "drawio-state.json")
    if refs and not drawio_path.exists():
        raise ValueError("Draw.io state missing")
    drawio_state = _read_json(drawio_path) if drawio_path.exists() else None
    drawio_config = _drawio_config(
        args, reliability, config, run_id, items, required_count=len(refs)
    )
    media_assets, resolutions, _ = validate_drawio_capture_state(
        drawio_state, run_id=run_id, selection_identity=selection["selection_identity"],
        observed_keys=observed_keys, config=drawio_config,
    )
    if drawio_state is not None and (drawio_state["failed"] != 0 or len(resolutions) != len(refs)):
        raise ValueError("Draw.io state incomplete")
    _verify_drawio_media_assets_on_disk(
        raw_root=Path(args.raw_root), media_assets=media_assets,
        profile=reliability, drawio_config=drawio_config,
    )
    packet = SubtreePacketExporter(validator=FoundationSchemaValidator()).publish(
        output_dir=Path(args.output_dir), documents=processed.documents,
        chunks=processed.chunks, media_assets=media_assets,
        summary={"page_corpus_complete": True, "drawio_references_observed": len(refs), "drawio_references_resolved": len(resolutions), "drawio_assets_failed": 0},
    )
    return {"status": "complete", "phase": "export", "format_version": packet["format_version"], "packet_published": True, "document_count": packet["document_count"], "chunk_count": packet["chunk_count"], "media_asset_count": packet["media_asset_count"]}


def _capture_delta_inventory_phase(args: argparse.Namespace, state: Path) -> dict[str, object]:
    if not args.run_id or not args.raw_root or not args.dataset_root or not args.base_dataset_version:
        raise ValueError("delta inventory inputs are required")
    run_id = _require_run_id(args.run_id)
    selection, items = _load_selection_payload(_selection_file(args, state, run_id), run_id=run_id, max_pages=args.max_pages)
    from knowledgenexus.foundation.application.use_cases.capture_delta_inventory import (
        CaptureDeltaInventory, DeltaInventoryCaptureRequest, selection_identity, scope_identity,
    )
    from knowledgenexus.foundation.domain.models.delta_inventory import (
        CurrentSelectionPage, DeltaInventoryScope, PriorConfluenceDocument,
    )
    from knowledgenexus.foundation.infrastructure.exporters.delta_snapshot_reader import PublishedSnapshotReader
    from knowledgenexus.foundation.infrastructure.raw_store import ConfluenceRawPageGenerationStore
    from knowledgenexus.foundation.infrastructure.sidecars import DeltaInventoryArtifactStore
    from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator
    from knowledgenexus.foundation.infrastructure.confluence import compose_live_subtree
    from knowledgenexus.foundation.infrastructure.confluence.confluence_retrying_http_transport import RetryingConfluenceHttpTransport
    from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import ActivateRawGenerationRequest

    profile = _validated_page_bound(args, _load_reliability_profile(args.reliability_profile_path))
    current = tuple(CurrentSelectionPage(item.page_id) for item in items)
    current_identity = selection_identity(current)
    payload = tuple({"page_id": item.page_id} for item in current)
    scope = DeltaInventoryScope(
        tuple(args.include_root_page_ids or ((args.root_page_id,) if args.root_page_id else ())),
        tuple(args.excluded_page_ids or ()),
        tuple(args.excluded_ancestor_page_ids or ()),
    )
    current_scope_identity = scope_identity(scope)
    reader = PublishedSnapshotReader(dataset_root=Path(args.dataset_root), validator=FoundationSchemaValidator())
    base = reader.read(args.base_dataset_version)
    prior: list[PriorConfluenceDocument] = []
    for row in base.streams["documents"]:
        if row.get("source_system") != "confluence" or row.get("source_type") not in {"wiki_page", "page"}:
            continue
        document_id = row.get("document_id")
        source_version = row.get("source_version")
        if type(document_id) is not str or not document_id.startswith("confluence:page:") or type(source_version) is not str or not source_version:
            raise ValueError("prior snapshot is invalid")
        page_id = document_id.removeprefix("confluence:page:")
        prior.append(PriorConfluenceDocument(page_id, document_id, source_version))
    source_config = _source_config(args, profile)
    composition = compose_live_subtree(raw_root=Path(args.raw_root), checkpoint_workspace=state, reliability_profile=profile, max_search_pages=profile["max_inventory_windows_per_root"])
    request = ActivateRawGenerationRequest(workspace=state, run_id=run_id, endpoint_url=os.environ.get("CONFLUENCE_BASE_URL", ""), source_config=source_config, reliability_profile=profile)
    with composition.checkpoint_run_port.activate_raw_generation(request) as session:
        transport = RetryingConfluenceHttpTransport(inner=composition.http_inner, profile=composition.retry_profile, monotonic_clock=time.monotonic, sleeper=time.sleep, attempt_reserver=session)
        capture_request = DeltaInventoryCaptureRequest(
            run_id=run_id, generation_id=run_id,
            accepted_base_dataset_version=args.base_dataset_version,
            current_selection_identity=current_identity,
            current_scope_identity=current_scope_identity,
            prior_documents=tuple(prior), current_selection=current, scope=scope,
            transport=transport,
            raw_page_store=ConfluenceRawPageGenerationStore(raw_root=Path(args.raw_root)),
            artifact_store=DeltaInventoryArtifactStore(state_root=state / "runs"),
            selection_payload=payload,
            max_response_bytes=profile["max_response_bytes_per_request"],
            max_artifact_bytes=profile["max_raw_bytes_per_run"],
            max_artifacts=profile["max_raw_artifacts_per_run"],
            minimum_free_disk_bytes=profile["minimum_free_disk_reserve_bytes"],
            max_requests=profile["max_total_requests_per_run"],
        )
        result = CaptureDeltaInventory().execute(capture_request)
        session.complete_session()
    return {"status": "complete", "phase": "capture-delta-inventory", "present_count": result.metrics.present_count, "source_deleted_count": result.metrics.source_deleted_count, "access_revoked_count": result.metrics.access_revoked_count, "moved_out_of_scope_count": result.metrics.moved_out_of_scope_count}


logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        state = Path(args.state_dir)
        if not state.is_absolute():
            raise ValueError("state directory must be absolute")
        handlers = {
            "inventory": _inventory_phase,
            "capture-pages": _capture_pages_phase,
            "process-pages": _process_pages_phase,
            "capture-drawio": _capture_drawio_phase,
            "capture-delta-inventory": _capture_delta_inventory_phase,
            "export": _export_phase,
        }
        result = handlers[args.phase](args, state)
        sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    except SystemExit as exc:
        return int(exc.code)
    except Exception:
        # stdout is a machine-read contract (exactly one JSON line), so the
        # payload stays byte-for-byte as it was -- but it collapses every
        # possible failure into one hardcoded word and drops the cause, which
        # left phase failures undiagnosable. Log the traceback before it goes.
        logger.exception(
            "Phase %s failed", getattr(locals().get("args", None), "phase", "?")
        )
        sys.stdout.write('{"status":"failed","error":"configuration"}\n')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
