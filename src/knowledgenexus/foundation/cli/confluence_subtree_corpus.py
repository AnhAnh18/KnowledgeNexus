"""CLI for the bounded Confluence subtree corpus harness."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from knowledgenexus.foundation.application.use_cases.confluence_subtree_corpus import (
    ConfluenceSubtreeCorpusConfig,
    ConfluenceSubtreeCorpusHarness,
    SubtreePacketExporter,
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
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        state = Path(args.state_dir)
        if not state.is_absolute(): raise ValueError("invalid configuration")
        config = ConfluenceSubtreeCorpusConfig(max_pages=args.max_pages, batch_size=args.batch_size)
        if args.phase == "inventory":
            if not args.selection_path: raise ValueError("selection input is required")
            selection = _load_subtree_selection(Path(args.selection_path), args.max_pages)
            state.mkdir(parents=True, exist_ok=True)
            (state / "inventory.json").write_text(json.dumps([{"page_id": x.page_id, "crawled_at": x.crawled_at, "expected_source_version": x.expected_source_version} for x in selection], sort_keys=True), encoding="utf-8")
            result = {"status":"complete", "phase":"inventory", "selected_pages":len(selection)}
        elif args.phase == "capture-pages":
            # The CLI is intentionally offline unless an approved adapter is
            # supplied by the embedding operator; consume fixture bodies when
            # present and preserve resumability.
            if not args.selection_path or not args.raw_root: raise ValueError("capture inputs are required")
            selection = _load_subtree_selection(Path(args.selection_path), args.max_pages)
            harness = ConfluenceSubtreeCorpusHarness(config=config, state_dir=state)
            source = Path(args.raw_root)
            result_obj = harness.capture_pages([x.page_id for x in selection], lambda pid: (source / f"{pid}.bin").read_bytes())
            result = {"status": result_obj["status"], "phase": args.phase, **result_obj}
        elif args.phase == "process-pages":
            if not args.raw_root or not args.selection_path or not args.profile_path or not args.tokenizer_assets_dir or not args.run_id:
                raise ValueError("process inputs are required")
            selection = _load_subtree_selection(Path(args.selection_path), args.max_pages)
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
            result = {"status": "complete", "phase": args.phase, "page_count": len(selection), "document_count": len(processed.documents), "chunk_count": len(processed.chunks)}
        elif args.phase == "capture-drawio":
            # Draw.io capture requires the production metadata/body adapters;
            # never report a zero-counter run as a complete corpus.
            raise ValueError("drawio capture adapters are required")
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
            if getattr(page_result.metrics, "failed_pages", 0) or drawio_observed:
                raise ValueError("corpus processing is incomplete")
            packet = SubtreePacketExporter(validator=FoundationSchemaValidator()).publish(output_dir=out, documents=page_result.documents, chunks=page_result.chunks, media_assets=(), summary={"page_corpus_complete": not bool(getattr(page_result.metrics, "failed_pages", 0)), "drawio_references_observed": drawio_observed, "drawio_references_resolved": 0, "drawio_assets_failed": drawio_observed})
            result = {"status": "complete", "phase": args.phase, "format_version": packet["format_version"], "packet_published": True, "document_count": packet["document_count"], "chunk_count": packet["chunk_count"], "media_asset_count": 0}
        sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    except SystemExit as exc:
        return int(exc.code)
    except Exception:
        sys.stdout.write('{"status":"failed","error":"configuration"}\n')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
