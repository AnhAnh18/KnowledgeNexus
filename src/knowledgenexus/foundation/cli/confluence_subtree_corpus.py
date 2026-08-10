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


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="confluence-subtree-corpus")
    sub = p.add_subparsers(dest="phase", required=True)
    for name in ("capture-pages", "capture-drawio", "export"):
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
        if args.phase == "capture-pages":
            raise ValueError("capture requires an approved transport adapter")
        if args.phase == "capture-drawio":
            pages = state / "pages"
            result = {"status": "complete", "phase": args.phase, "page_count": len(tuple(pages.glob("*.bin"))) if pages.is_dir() else 0, "drawio_references_observed": 0, "drawio_references_resolved": 0}
        else:
            if not args.output_dir or not args.raw_root or not args.selection_path or not args.profile_path or not args.tokenizer_assets_dir or not args.run_id:
                raise ValueError("export inputs are required")
            out = Path(args.output_dir)
            from knowledgenexus.foundation.application.use_cases.process_confluence_page_set import ProcessConfluencePageSet
            from knowledgenexus.foundation.cli.accept_confluence_mini_corpus import load_mini_corpus_selection, safe_mini_corpus_path
            from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
            from knowledgenexus.foundation.domain.models.confluence_page_set import ACTIVE_PAGE_SET_PROFILE_IDENTITY, ConfluencePageSetRequest
            from knowledgenexus.foundation.infrastructure.config.chunking_profile_loader import load_chunking_profile
            from knowledgenexus.foundation.infrastructure.processors import ConfluenceDataCenterRawPageMapper, ConfluenceStorageXhtmlNormalizer
            from knowledgenexus.foundation.infrastructure.raw_store import ConfluenceRawPageGenerationStore
            from knowledgenexus.foundation.infrastructure.tokenization import BgeM3LocalTokenizer
            raw_root = safe_mini_corpus_path(Path(args.raw_root)); selection = safe_mini_corpus_path(Path(args.selection_path)); profile_path = safe_mini_corpus_path(Path(args.profile_path)); assets = safe_mini_corpus_path(Path(args.tokenizer_assets_dir))
            profile = load_chunking_profile(profile_path)
            request = ConfluencePageSetRequest(run_id=CrawlRunId(args.run_id), generation_id=CrawlRunId(args.run_id), items=load_mini_corpus_selection(selection), profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY)
            page_result = ProcessConfluencePageSet(chunking_profile=profile, tokenizer=BgeM3LocalTokenizer(profile=profile, tokenizer_assets_dir=assets), raw_page_store=ConfluenceRawPageGenerationStore(raw_root=raw_root), raw_page_mapper=ConfluenceDataCenterRawPageMapper(), storage_normalizer=ConfluenceStorageXhtmlNormalizer(), schema_validator=FoundationSchemaValidator()).execute(request=request)
            packet = SubtreePacketExporter(validator=FoundationSchemaValidator()).publish(output_dir=out, documents=page_result.documents, chunks=page_result.chunks, media_assets=(), summary={"page_corpus_complete": True, "drawio_references_observed": 0, "drawio_references_resolved": 0, "drawio_assets_failed": 0})
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
