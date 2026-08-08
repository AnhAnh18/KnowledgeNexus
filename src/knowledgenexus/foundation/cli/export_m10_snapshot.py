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
from typing import NoReturn

from knowledgenexus.foundation.application.use_cases.export_m10_snapshot import (
    M10SnapshotExportFailure,
)
from knowledgenexus.foundation.infrastructure.exporters.m10_snapshot_exporter import M10FullSnapshotExporter
from knowledgenexus.foundation.domain.models.m10_snapshot import M10SnapshotResult
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator


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
    parser.parse_args([] if argv is None else argv)
    return argparse.Namespace()


def _fail(category: str, code: int) -> int:
    sys.stderr.write(json.dumps({"status": "failed", "category": category}, sort_keys=True, allow_nan=False) + "\n")
    return code


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
        _parse_args(argv)
        if request is None or confluence_adapter is None or git_adapter is None:
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
