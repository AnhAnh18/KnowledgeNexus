"""Sanitized offline M10 full-snapshot CLI boundary.

Adapters are dependencies of the application boundary and are intentionally
not constructed here; this entry point cannot reach network, credential, raw,
or checkpoint stores.
"""
from __future__ import annotations

import argparse
import json
import logging
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
from knowledgenexus.foundation.infrastructure.exporters.m10_snapshot_exporter import M10FullSnapshotExporter
from knowledgenexus.foundation.domain.models.m10_snapshot import M10MediaPolicy, M10SnapshotResult
from knowledgenexus.foundation.ports.path_safety import require_plain_directory_chain, require_plain_file
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator
from knowledgenexus.foundation.infrastructure.config import load_chunking_profile, load_jira_relation_profile
from knowledgenexus.foundation.infrastructure.raw_store import ConfluenceRawPageGenerationStore
from knowledgenexus.foundation.infrastructure.processors import ConfluenceDataCenterRawPageMapper, ConfluenceStorageXhtmlNormalizer
from knowledgenexus.foundation.infrastructure.tokenization import BgeM3LocalTokenizer
from knowledgenexus.foundation.infrastructure.adapters.m10_composition_root import ConfluenceM10CompositionRoot
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
    parser.add_argument("--chunking-profile")
    parser.add_argument("--tokenizer-assets-dir")
    parser.add_argument("--jira-relation-profile")
    parser.add_argument("--dataset-root")
    parser.add_argument("--ordered-page-id", "--ordered-page-ids", action="append", dest="ordered_page_ids")
    parser.add_argument("--selection-path")
    parser.add_argument("--space-key", "--space-keys", action="append", dest="space_keys")
    parser.add_argument("--root-page-id", "--root-page-ids", action="append", dest="root_page_ids")
    parser.add_argument("--exclude-page-id", "--exclusions", action="append", dest="excluded_page_ids")
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
    directory_options = ("raw_generation_root", "tokenizer_assets_dir", "dataset_root", "git_repository_root")
    file_options = ("chunking_profile", "jira_relation_profile", "selection_path")
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
    pages = tuple(args.ordered_page_ids or ())
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
    request = M10SnapshotRequest(
        run_id=run_id, generation_id=generation_id,
        confluence_scope=M10ConfluenceScope("confluence", spaces, roots, tuple(sorted(set(pages)))),
        confluence_exclusions=tuple(M10ConfluenceExclusion(x, "exclude_page") for x in sorted(set(args.excluded_page_ids or ()))),
        ordered_page_ids=pages, raw_generation_id=_required(args, "generation_id"),
        git_repository=_required(args, "git_repository"), git_branch=_required(args, "git_branch"),
        git_commit=_required(args, "git_commit"), media_policy=_media_policy(args.media_policy),
        profile_bundle=bundle, generated_at=_required(args, "generated_at"),
        dataset_root=dataset_root, export_mode=args.export_mode,
        profile_identity=identity, base_dataset_version=args.base_dataset_version,
    )
    tokenizer = BgeM3LocalTokenizer(profile=chunking, tokenizer_assets_dir=assets)
    confluence = ConfluenceM10CompositionRoot.build(
        raw_page_store=ConfluenceRawPageGenerationStore(raw_root=raw_root), tokenizer=tokenizer,
        chunking_profile=chunking, raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
    )
    return request, confluence, _EmptyGitAdapter()


def run(*, request: object, confluence_adapter: object, git_adapter: object, validator: FoundationSchemaValidator | None = None):
    """Run the injected offline boundary; useful for tests and embedding."""
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
            request, confluence_adapter, git_adapter = _build_operator_inputs(parsed)
        elif request is None or confluence_adapter is None or git_adapter is None:
            raise M10SnapshotExportFailure("invalid_request")
        result = run(request=request, confluence_adapter=confluence_adapter, git_adapter=git_adapter, validator=validator)
    except SystemExit as exc:
        if type(exc.code) is int:
            return exc.code
        return _fail("unexpected", EXIT_UNEXPECTED)
    except _ConfigurationError:
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
