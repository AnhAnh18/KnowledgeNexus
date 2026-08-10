"""CLI for the bounded Confluence subtree corpus harness."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from knowledgenexus.foundation.application.use_cases.confluence_subtree_corpus import (
    ConfluenceSubtreeCorpusConfig,
    ConfluenceSubtreeCorpusHarness,
    SubtreePacketExporter,
    DrawioReference,
    capture_drawio_with_production_components,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator
from knowledgenexus.foundation.domain.models.confluence_page_set import ConfluencePageWorkItem


def _load_subtree_selection(path: Path, max_pages: int) -> tuple[ConfluencePageWorkItem, ...]:
    if not path.is_absolute() or type(max_pages) is not int or max_pages <= 0 or max_pages > 5000:
        raise ValueError("invalid selection")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not list or not payload or len(payload) > max_pages or len(payload) > 5000:
        raise ValueError("invalid selection")
    return tuple(ConfluencePageWorkItem(page_id=x["page_id"], crawled_at=x["crawled_at"], expected_source_version=x["expected_source_version"]) for x in payload)

def _atomic_json(path: Path, payload: object) -> None:
    if not path.is_absolute():
        raise ValueError("state path is invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise ValueError("state artifact is unsafe")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)

def _state_path(state: Path, run_id: str, name: str) -> Path:
    if type(run_id) is not str or not run_id:
        raise ValueError("run id is invalid")
    if not state.is_absolute():
        raise ValueError("state path is invalid")
    root = state / "runs" / run_id
    if root.exists() and not root.is_dir():
        raise ValueError("state path is invalid")
    root.mkdir(parents=True, exist_ok=True)
    return root / name


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="confluence-subtree-corpus")
    sub = p.add_subparsers(dest="phase", required=True)
    for name in ("inventory", "capture-pages", "process-pages", "capture-drawio", "export"):
        q = sub.add_parser(name)
        q.add_argument("--state-dir", required=True)
        q.add_argument("--max-pages", type=int, required=True)
        q.add_argument("--batch-size", type=int, default=100)
        q.add_argument("--output-dir")
        q.add_argument("--raw-root")
        q.add_argument("--selection-path")
        q.add_argument("--profile-path")
        q.add_argument("--tokenizer-assets-dir")
        q.add_argument("--run-id")
        q.add_argument("--resume-run-id")
        q.add_argument("--resume-unique", action="store_true")
        q.add_argument("--space-key")
        q.add_argument("--root-page-id")
        q.add_argument("--drawio-references-path")
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        state = Path(args.state_dir)
        if not state.is_absolute(): raise ValueError("invalid configuration")
        config = ConfluenceSubtreeCorpusConfig(max_pages=args.max_pages, batch_size=args.batch_size)
        if args.phase == "inventory":
            if args.space_key and args.root_page_id and args.profile_path:
                from knowledgenexus.foundation.application.use_cases.execute_bounded_confluence_inventory import ExecuteBoundedConfluenceInventory
                from knowledgenexus.foundation.domain.models.confluence_source_config import ConfluenceIncludeRoot, ConfluenceSourceConfig
                from knowledgenexus.foundation.infrastructure.confluence import compose_live_subtree
                from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import ResumeExplicitRunRequest, ResumeUniqueIncompleteRunRequest, StartNewRunRequest
                profile = json.loads(Path(args.profile_path).read_text(encoding="utf-8"))
                source_config = ConfluenceSourceConfig(source_id="confluence-root1", space_key=args.space_key, include_roots=(ConfluenceIncludeRoot(page_id=args.root_page_id),))
                composition = compose_live_subtree(raw_root=Path(args.raw_root or (state / "raw")), checkpoint_workspace=state, reliability_profile=profile, max_search_pages=args.max_pages)
                if args.resume_run_id:
                    from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
                    request = ResumeExplicitRunRequest(workspace=state, run_id=CrawlRunId(args.resume_run_id), endpoint_url=os.environ.get("CONFLUENCE_BASE_URL", ""), source_config=source_config, reliability_profile=profile)
                elif args.resume_unique:
                    request = ResumeUniqueIncompleteRunRequest(workspace=state, endpoint_url=os.environ.get("CONFLUENCE_BASE_URL", ""), source_config=source_config, reliability_profile=profile)
                else:
                    request = StartNewRunRequest(workspace=state, endpoint_url=os.environ.get("CONFLUENCE_BASE_URL", ""), source_config=source_config, reliability_profile=profile)
                # The durable executor creates a retry transport per activated
                # checkpoint session; reservations therefore survive process
                # restarts and are enforced before every outbound attempt.
                result_obj = composition.inventory_use_case(max_search_pages=args.max_pages).execute(request=request)
                snapshot = result_obj.snapshot
                if snapshot is None:
                    raise ValueError("inventory snapshot missing")
                from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
                from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import ResumeExplicitRunRequest
                with composition.checkpoint_run_port.resume_explicit_run_id(ResumeExplicitRunRequest(workspace=state, run_id=snapshot.run_id, endpoint_url=os.environ.get("CONFLUENCE_BASE_URL", ""), source_config=source_config, reliability_profile=profile)) as session:
                    from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import InventoryOccurrence
                    occurrences = tuple(item for item in session.stream_inventory_occurrences(batch_size=100) if type(item) is InventoryOccurrence)
                occurrences = tuple(sorted(occurrences, key=lambda x: (x.include_root_ordinal, x.window_start, x.item_ordinal, x.page_id)))
                if any(x.metadata.updated_at is None for x in occurrences):
                    raise ValueError("inventory timestamp missing")
                rows = [{"page_id": x.page_id, "crawled_at": x.metadata.updated_at, "expected_source_version": x.metadata.source_version} for x in occurrences]
                if len(rows) > args.max_pages:
                    raise ValueError("inventory exceeds bound")
                rid = str(snapshot.run_id)
                _atomic_json(_state_path(state, rid, "inventory-selection.json"), {"run_id": rid, "generation_id": rid, "selection_identity": hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "items": rows})
                _atomic_json(state / "inventory.json", rows)
                result = {"status": result_obj.status, "phase": args.phase, "selected_pages": len(rows), "run_id": rid}
            elif not args.selection_path: raise ValueError("selection input is required")
            else:
                selection = _load_subtree_selection(Path(args.selection_path), args.max_pages)
                state.mkdir(parents=True, exist_ok=True)
                rows = [{"page_id": x.page_id, "crawled_at": x.crawled_at, "expected_source_version": x.expected_source_version} for x in selection]
                _atomic_json(state / "inventory.json", rows)
                result = {"status":"complete", "phase":"inventory", "selected_pages":len(selection)}
        elif args.phase == "capture-pages":
            if not args.raw_root or not args.profile_path or not args.run_id or not args.space_key or not args.root_page_id:
                raise ValueError("live capture configuration is required")
            from knowledgenexus.foundation.infrastructure.confluence import compose_live_subtree
            from knowledgenexus.foundation.application.use_cases.capture_confluence_subtree_pages import CaptureConfluenceSubtreePages
            from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_page_orphan_inspector import ConfluenceRawPageOrphanInspector
            from knowledgenexus.foundation.infrastructure.confluence.confluence_retrying_http_transport import RetryingConfluenceHttpTransport
            from knowledgenexus.foundation.infrastructure.confluence.confluence_data_center_page_adapter import ConfluenceDataCenterPageAdapter
            from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
            from knowledgenexus.foundation.domain.models.confluence_source_config import ConfluenceIncludeRoot, ConfluenceSourceConfig
            from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import ResumeExplicitRunRequest
            profile = json.loads(Path(args.profile_path).read_text(encoding="utf-8"))
            source_config = ConfluenceSourceConfig(source_id="confluence-root1", space_key=args.space_key, include_roots=(ConfluenceIncludeRoot(page_id=args.root_page_id),))
            composition = compose_live_subtree(raw_root=Path(args.raw_root), checkpoint_workspace=state, reliability_profile=profile, max_search_pages=args.max_pages)
            request = ResumeExplicitRunRequest(workspace=state, run_id=CrawlRunId(args.run_id), endpoint_url=os.environ.get("CONFLUENCE_BASE_URL", ""), source_config=source_config, reliability_profile=profile)
            with composition.checkpoint_run_port.resume_explicit_run_id(request) as outcome:
                if not callable(getattr(outcome, "stream_inventory_occurrences", None)):
                    raise ValueError("run selection failed")
                page_transport = RetryingConfluenceHttpTransport(inner=composition.http_inner, profile=composition.retry_profile, monotonic_clock=time.monotonic, sleeper=time.sleep, attempt_reserver=outcome)
                use_case = CaptureConfluenceSubtreePages(state_session=outcome, orphan_inspector=ConfluenceRawPageOrphanInspector(raw_root=Path(args.raw_root)), page_fetcher=ConfluenceDataCenterPageAdapter(transport=page_transport), raw_page_store=composition.raw_page_store)
                from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import InventoryOccurrence
                occurrences = tuple(item for item in outcome.stream_inventory_occurrences(batch_size=100) if type(item) is InventoryOccurrence)
                result_obj = use_case.run(run_id=CrawlRunId(args.run_id), occurrences=occurrences, stop_after_batches=None)
            result = {"status": "complete" if result_obj.complete else "failed", "phase": args.phase, "captured": result_obj.captured, "replayed": result_obj.replayed, "skipped": result_obj.skipped, "failed": result_obj.failed}
        elif args.phase == "process-pages":
            if not args.raw_root or not args.profile_path or not args.tokenizer_assets_dir or not args.run_id:
                raise ValueError("process inputs are required")
            selection_file = Path(args.selection_path) if args.selection_path else _state_path(state, args.run_id, "inventory-selection.json")
            if selection_file.name == "inventory-selection.json":
                envelope = json.loads(selection_file.read_text(encoding="utf-8")); selection_rows = envelope.get("items", envelope)
                selection = tuple(ConfluencePageWorkItem(page_id=x["page_id"], crawled_at=x["crawled_at"], expected_source_version=x.get("expected_source_version")) for x in selection_rows)
            else:
                selection = _load_subtree_selection(selection_file, args.max_pages)
            from knowledgenexus.foundation.application.use_cases.process_confluence_page_set import ProcessConfluencePageSet
            from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
            from knowledgenexus.foundation.domain.models.confluence_page_set import ACTIVE_PAGE_SET_PROFILE_IDENTITY, ConfluencePageSetRequest
            from knowledgenexus.foundation.infrastructure.config.chunking_profile_loader import load_chunking_profile
            from knowledgenexus.foundation.infrastructure.processors import ConfluenceDataCenterRawPageMapper, ConfluenceStorageXhtmlNormalizer
            from knowledgenexus.foundation.infrastructure.raw_store import ConfluenceRawPageGenerationStore
            from knowledgenexus.foundation.infrastructure.tokenization import BgeM3LocalTokenizer
            profile = load_chunking_profile(Path(args.profile_path))
            request = ConfluencePageSetRequest(run_id=CrawlRunId(args.run_id), generation_id=CrawlRunId(args.run_id), items=selection, profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY)
            processed = ProcessConfluencePageSet(chunking_profile=profile, tokenizer=BgeM3LocalTokenizer(profile=profile, tokenizer_assets_dir=Path(args.tokenizer_assets_dir)), raw_page_store=ConfluenceRawPageGenerationStore(raw_root=Path(args.raw_root)), raw_page_mapper=ConfluenceDataCenterRawPageMapper(), storage_normalizer=ConfluenceStorageXhtmlNormalizer(), schema_validator=FoundationSchemaValidator()).execute(request=request)
            if not processed.documents or not processed.chunks or getattr(processed.metrics, "failed_pages", 0):
                raise ValueError("page processing incomplete")
            refs = []
            for page_id, intents in processed.reference_intents_by_page.items():
                for intent in intents:
                    if getattr(intent, "kind", None) == "drawio":
                        refs.append({"parent_page_id": page_id, "filename": intent.target_identity, "source_version": intent.placeholder_identity})
            refs.sort(key=lambda x: (x["parent_page_id"], x["filename"], x["source_version"]))
            selection_identity = hashlib.sha256(json.dumps([{ "page_id": x.page_id, "crawled_at": x.crawled_at, "expected_source_version": x.expected_source_version} for x in selection], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            _atomic_json(_state_path(state, args.run_id, "processing-state.json"), {"run_id": args.run_id, "generation_id": args.run_id, "selection_identity": selection_identity, "page_count": len(selection), "completed_pages": len(selection) - getattr(processed.metrics, "failed_pages", 0), "failed_pages": getattr(processed.metrics, "failed_pages", 0), "drawio_references": refs})
            result = {"status": "complete", "phase": args.phase, "page_count": len(selection), "document_count": len(processed.documents), "chunk_count": len(processed.chunks)}
        elif args.phase == "capture-drawio":
            if not (args.space_key and args.root_page_id and args.profile_path and args.raw_root and args.run_id):
                raise ValueError("drawio capture configuration is required")
            from knowledgenexus.foundation.infrastructure.confluence import compose_live_subtree
            from knowledgenexus.foundation.domain.models.media_body_materialization import MediaBodyStoreBudget
            processing_state = _state_path(state, args.run_id, "processing-state.json")
            refs_payload = json.loads(processing_state.read_text(encoding="utf-8")).get("drawio_references", [])
            if type(refs_payload) is not list:
                raise ValueError("drawio references are invalid")
            refs = tuple(DrawioReference(parent_page_id=x["parent_page_id"], filename=x["filename"], source_version=x["source_version"]) for x in refs_payload)
            profile = json.loads(Path(args.profile_path).read_text(encoding="utf-8"))
            required_budget_keys = ("drawio_max_body_bytes", "drawio_max_total_bytes", "minimum_free_disk_reserve_bytes")
            if type(profile) is not dict or any(k not in profile or type(profile[k]) is not int or isinstance(profile[k], bool) or profile[k] <= 0 for k in required_budget_keys):
                raise ValueError("drawio budgets are required")
            if profile["drawio_max_body_bytes"] > profile["drawio_max_total_bytes"] or profile["drawio_max_total_bytes"] < profile["drawio_max_body_bytes"]:
                raise ValueError("drawio budgets are contradictory")
            composition = compose_live_subtree(raw_root=Path(args.raw_root), checkpoint_workspace=state, reliability_profile=profile, max_search_pages=args.max_pages)
            budget = MediaBodyStoreBudget(max_body_bytes=profile["drawio_max_body_bytes"], max_total_bytes=profile["drawio_max_total_bytes"], minimum_free_disk_reserve_bytes=profile["minimum_free_disk_reserve_bytes"])
            observer, materializer, processor = composition.attachment_components(attachment_root=Path(args.raw_root) / "attachments", budget=budget)
            result = {"status": "complete", "phase": args.phase, **capture_drawio_with_production_components(references=refs, attachment_observer=observer, body_materializer=materializer, media_processor=processor, config=config, state_path=_state_path(state, args.run_id, "drawio-state.json"))}
            if result["drawio_references_resolved"] != result["drawio_references_observed"]:
                raise ValueError("drawio capture incomplete")
        elif args.phase == "export":
            if not args.output_dir or not args.raw_root or not args.selection_path or not args.profile_path or not args.tokenizer_assets_dir or not args.run_id:
                raise ValueError("export inputs are required")
            out = Path(args.output_dir)
            from knowledgenexus.foundation.application.use_cases.process_confluence_page_set import ProcessConfluencePageSet
            from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
            from knowledgenexus.foundation.domain.models.confluence_page_set import ACTIVE_PAGE_SET_PROFILE_IDENTITY, ConfluencePageSetRequest
            from knowledgenexus.foundation.infrastructure.config.chunking_profile_loader import load_chunking_profile
            from knowledgenexus.foundation.infrastructure.processors import ConfluenceDataCenterRawPageMapper, ConfluenceStorageXhtmlNormalizer
            from knowledgenexus.foundation.infrastructure.raw_store import ConfluenceRawPageGenerationStore
            from knowledgenexus.foundation.infrastructure.tokenization import BgeM3LocalTokenizer
            raw_root = Path(args.raw_root); selection = Path(args.selection_path); profile_path = Path(args.profile_path); assets = Path(args.tokenizer_assets_dir)
            profile = load_chunking_profile(profile_path)
            request = ConfluencePageSetRequest(run_id=CrawlRunId(args.run_id), generation_id=CrawlRunId(args.run_id), items=_load_subtree_selection(selection, args.max_pages), profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY)
            page_result = ProcessConfluencePageSet(chunking_profile=profile, tokenizer=BgeM3LocalTokenizer(profile=profile, tokenizer_assets_dir=assets), raw_page_store=ConfluenceRawPageGenerationStore(raw_root=raw_root), raw_page_mapper=ConfluenceDataCenterRawPageMapper(), storage_normalizer=ConfluenceStorageXhtmlNormalizer(), schema_validator=FoundationSchemaValidator()).execute(request=request)
            intents = tuple(intent for values in page_result.reference_intents_by_page.values() for intent in values)
            drawio_observed = sum(getattr(intent, "kind", None) == "drawio" for intent in intents)
            processing_state_path = _state_path(state, args.run_id, "processing-state.json")
            processing_state = json.loads(processing_state_path.read_text(encoding="utf-8"))
            current_refs = sorted(tuple((x["parent_page_id"], x["filename"], x["source_version"])) for x in processing_state.get("drawio_references", []))
            drawio_state_path = _state_path(state, args.run_id, "drawio-state.json")
            drawio_state = json.loads(drawio_state_path.read_text(encoding="utf-8")) if drawio_state_path.exists() else {"observed": [], "resolved": [], "failed": 0, "media_assets": []}
            observed_state = sorted(tuple(x) for x in drawio_state.get("observed", []))
            if getattr(page_result.metrics, "failed_pages", 0) or (current_refs and (not drawio_state_path.exists() or observed_state != current_refs)) or len(drawio_state.get("resolved", ())) != len(drawio_state.get("observed", ())) or drawio_state.get("failed", 0) != 0:
                raise ValueError("corpus processing is incomplete")
            media_assets = tuple(drawio_state.get("media_assets", ()))
            packet = SubtreePacketExporter(validator=FoundationSchemaValidator()).publish(output_dir=out, documents=page_result.documents, chunks=page_result.chunks, media_assets=media_assets, summary={"page_corpus_complete": not bool(getattr(page_result.metrics, "failed_pages", 0)), "drawio_references_observed": len(drawio_state.get("observed", ())), "drawio_references_resolved": len(drawio_state.get("resolved", ())), "drawio_assets_failed": drawio_state.get("failed", 0)})
            result = {"status": "complete", "phase": args.phase, "format_version": packet["format_version"], "packet_published": True, "document_count": packet["document_count"], "chunk_count": packet["chunk_count"], "media_asset_count": packet["media_asset_count"]}
        sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    except SystemExit as exc:
        return int(exc.code)
    except Exception:
        sys.stdout.write('{"status":"failed","error":"configuration"}\n')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
