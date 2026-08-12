"""Sanitized operator CLI for the Foundation F4/F7 gate evaluators.

The input file is a small JSON metadata envelope.  It may contain only the
fields accepted by :mod:`foundation_gate_inputs`; page text, URLs, credentials,
and processor payloads are not accepted at this boundary.  The command emits
one aggregate JSON line and never includes malformed input or filesystem paths
in its output.

Examples::

    python -m knowledgenexus.foundation.cli.evaluate_foundation_gates \
        --gate media --input media-gate.json
    python -m knowledgenexus.foundation.cli.evaluate_foundation_gates \
        --gate scale --input scale-gate.json
    python -m knowledgenexus.foundation.cli.evaluate_foundation_gates \
        --gate ocr --input ocr-approval.json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from knowledgenexus.foundation.application.use_cases.evaluate_foundation_gates import (
    EvaluateBoundedMediaCorpusAcceptance,
    EvaluateOcrEngineApproval,
    EvaluateScaleGateEvidence,
)
from knowledgenexus.foundation.domain.models.foundation_gate import OcrEngineApproval
from knowledgenexus.foundation.domain.models.foundation_gate_inputs import (
    BoundedMediaGateRequest,
    PublishedSnapshotReadback,
    SanitizedMediaProcessorOutcome,
    SanitizedMediaProcessorRun,
    ScaleGateRequest,
)
from knowledgenexus.foundation.domain.models.media_ocr import OcrLimits


EXIT_SUCCESS = 0
EXIT_UNEXPECTED = 1
EXIT_CONFIGURATION = 2
EXIT_INVALID_INPUT = 20
EXIT_GATE_FAILED = 21

# A bounded metadata file is intentional: this command is not a raw-content
# transport and should fail before allocating unbounded JSON structures.
_MAX_INPUT_BYTES = 1_048_576
_FORBIDDEN_PATH_PARTS = frozenset({".env", ".local_ai", "evidence", "tool_trreport", "raw", "runtime"})
_MEDIA_RUN_FIELDS = frozenset({
    "outcomes", "expected_media_ids", "source_digest_before",
    "source_digest_after", "write_digest_before", "write_digest_after",
})
_MEDIA_OUTCOME_FIELDS = frozenset({"media_id", "kind", "status", "result_digest", "reason_code"})
_READBACK_FIELDS = frozenset({
    "dataset_version", "content_digest", "observed_pages", "stream_counts",
    "readback_valid", "relation_closed", "acl_closed", "sync_closed",
    "atomic_publish", "no_clobber", "sanitized_output", "transport",
    "rss_baseline_bytes", "rss_peak_bytes", "duration_milliseconds",
})
_MEDIA_REQUEST_FIELDS = frozenset({"first_run", "second_run", "evidence_kind", "real_capture_attested", "transport", "media_scope"})
_SCALE_REQUEST_FIELDS = frozenset({
    "profile_id", "target_pages", "first_readback", "second_readback", "evidence_kind",
})
_OCR_FIELDS = frozenset({
    "status", "engine_id", "engine_version", "runtime_identity",
    "model_identity", "build_identity", "offline_only", "limits",
    "evidence_kind", "evidence_digest", "approved_at", "failure_reason",
})
_OCR_LIMIT_FIELDS = frozenset({
    "max_input_bytes", "max_raster_bytes", "max_output_bytes", "max_images",
    "max_seconds", "min_confidence", "min_text_bytes",
})


class _ConfigurationError(Exception):
    """Invalid command-line configuration without retaining its values."""


class _InputError(ValueError):
    """Malformed or non-sanitized metadata input."""


class _SanitizedParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse's default error includes the offending argument.  Operator
        # paths may be sensitive, so expose only a stable category.
        raise _ConfigurationError


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _SanitizedParser(prog="evaluate-foundation-gates", add_help=True)
    parser.add_argument("--gate", choices=("media", "ocr", "scale"), required=True)
    parser.add_argument("--input", required=True, dest="input_path")
    args = parser.parse_args(argv)
    if type(args.input_path) is not str or not args.input_path:
        raise _ConfigurationError
    return args


def _object(value: object, fields: frozenset[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise _InputError
    return value


def _optional_object(value: object, fields: frozenset[str]) -> dict[str, object]:
    if type(value) is not dict:
        raise _InputError
    keys = set(value)
    if not keys <= fields:
        raise _InputError
    return value


def _media_outcome(value: object) -> SanitizedMediaProcessorOutcome:
    payload = _optional_object(value, _MEDIA_OUTCOME_FIELDS)
    required = {"media_id", "kind", "status", "result_digest"}
    if set(payload) < required:
        raise _InputError
    return SanitizedMediaProcessorOutcome(
        media_id=payload["media_id"],  # type: ignore[arg-type]
        kind=payload["kind"],  # type: ignore[arg-type]
        status=payload["status"],  # type: ignore[arg-type]
        result_digest=payload["result_digest"],  # type: ignore[arg-type]
        reason_code=payload.get("reason_code"),  # type: ignore[arg-type]
    )


def _media_run(value: object) -> SanitizedMediaProcessorRun:
    payload = _object(value, _MEDIA_RUN_FIELDS)
    outcomes = payload["outcomes"]
    expected = payload["expected_media_ids"]
    if type(outcomes) is not list or type(expected) is not list:
        raise _InputError
    return SanitizedMediaProcessorRun(
        outcomes=tuple(_media_outcome(item) for item in outcomes),
        expected_media_ids=tuple(expected),  # type: ignore[arg-type]
        source_digest_before=payload["source_digest_before"],  # type: ignore[arg-type]
        source_digest_after=payload["source_digest_after"],  # type: ignore[arg-type]
        write_digest_before=payload["write_digest_before"],  # type: ignore[arg-type]
        write_digest_after=payload["write_digest_after"],  # type: ignore[arg-type]
    )


def _stream_counts(value: object) -> tuple[tuple[str, int], ...]:
    if type(value) is not list:
        raise _InputError
    result: list[tuple[str, int]] = []
    for item in value:
        if type(item) is not list or len(item) != 2:
            raise _InputError
        stream, count = item
        if type(stream) is not str or type(count) is not int:
            raise _InputError
        result.append((stream, count))
    return tuple(result)


def _readback(value: object) -> PublishedSnapshotReadback:
    payload = _optional_object(value, _READBACK_FIELDS)
    required = {
        "dataset_version", "content_digest", "observed_pages", "stream_counts",
        "readback_valid", "relation_closed", "acl_closed", "sync_closed",
        "atomic_publish", "no_clobber", "sanitized_output", "transport",
    }
    if set(payload) < required:
        raise _InputError
    return PublishedSnapshotReadback(
        dataset_version=payload["dataset_version"],  # type: ignore[arg-type]
        content_digest=payload["content_digest"],  # type: ignore[arg-type]
        observed_pages=payload["observed_pages"],  # type: ignore[arg-type]
        stream_counts=_stream_counts(payload["stream_counts"]),
        readback_valid=payload["readback_valid"],  # type: ignore[arg-type]
        relation_closed=payload["relation_closed"],  # type: ignore[arg-type]
        acl_closed=payload["acl_closed"],  # type: ignore[arg-type]
        sync_closed=payload["sync_closed"],  # type: ignore[arg-type]
        atomic_publish=payload["atomic_publish"],  # type: ignore[arg-type]
        no_clobber=payload["no_clobber"],  # type: ignore[arg-type]
        sanitized_output=payload["sanitized_output"],  # type: ignore[arg-type]
        transport=payload["transport"],  # type: ignore[arg-type]
        rss_baseline_bytes=payload.get("rss_baseline_bytes"),  # type: ignore[arg-type]
        rss_peak_bytes=payload.get("rss_peak_bytes"),  # type: ignore[arg-type]
        duration_milliseconds=payload.get("duration_milliseconds"),  # type: ignore[arg-type]
    )


def _ocr_limits(value: object) -> OcrLimits:
    if type(value) is not dict or set(value) != _OCR_LIMIT_FIELDS:
        raise _InputError
    return OcrLimits(
        max_input_bytes=value["max_input_bytes"],  # type: ignore[arg-type]
        max_raster_bytes=value["max_raster_bytes"],  # type: ignore[arg-type]
        max_output_bytes=value["max_output_bytes"],  # type: ignore[arg-type]
        max_images=value["max_images"],  # type: ignore[arg-type]
        max_seconds=value["max_seconds"],  # type: ignore[arg-type]
        min_confidence=value["min_confidence"],  # type: ignore[arg-type]
        min_text_bytes=value["min_text_bytes"],  # type: ignore[arg-type]
    )


def _ocr_request(payload: object) -> OcrEngineApproval:
    data = _optional_object(payload, _OCR_FIELDS)
    if "status" not in data:
        raise _InputError
    return OcrEngineApproval(
        status=data["status"],  # type: ignore[arg-type]
        engine_id=data.get("engine_id"),  # type: ignore[arg-type]
        engine_version=data.get("engine_version"),  # type: ignore[arg-type]
        runtime_identity=data.get("runtime_identity"),  # type: ignore[arg-type]
        model_identity=data.get("model_identity"),  # type: ignore[arg-type]
        build_identity=data.get("build_identity"),  # type: ignore[arg-type]
        offline_only=data.get("offline_only"),  # type: ignore[arg-type]
        limits=_ocr_limits(data["limits"]) if "limits" in data else OcrLimits(),
        evidence_kind=data.get("evidence_kind"),  # type: ignore[arg-type]
        evidence_digest=data.get("evidence_digest"),  # type: ignore[arg-type]
        approved_at=data.get("approved_at"),  # type: ignore[arg-type]
        failure_reason=data.get("failure_reason"),  # type: ignore[arg-type]
    )


def _request(gate: str, payload: object) -> BoundedMediaGateRequest | OcrEngineApproval | ScaleGateRequest:
    if gate == "ocr":
        return _ocr_request(payload)
    if gate == "media":
        if type(payload) is not dict or not {"first_run", "second_run", "evidence_kind"} <= set(payload) or set(payload) - _MEDIA_REQUEST_FIELDS:
            raise _InputError
        data = payload
        return BoundedMediaGateRequest(
            first_run=_media_run(data["first_run"]),
            second_run=_media_run(data["second_run"]),
            evidence_kind=data["evidence_kind"],  # type: ignore[arg-type]
            real_capture_attested=data.get("real_capture_attested", False),  # type: ignore[arg-type]
            transport=data.get("transport", "offline_fixture"),  # type: ignore[arg-type]
            media_scope=data.get("media_scope", "all_media"),  # type: ignore[arg-type]
        )
    data = _object(payload, _SCALE_REQUEST_FIELDS)
    return ScaleGateRequest(
        profile_id=data["profile_id"],  # type: ignore[arg-type]
        target_pages=data["target_pages"],  # type: ignore[arg-type]
        first_readback=_readback(data["first_readback"]),
        second_readback=_readback(data["second_readback"]),
        evidence_kind=data["evidence_kind"],  # type: ignore[arg-type]
    )


def _load(path_value: str) -> object:
    def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError
            result[key] = item
        return result

    try:
        path = _safe_input_path(path_value)
        if not path.is_file() or path.stat().st_size > _MAX_INPUT_BYTES:
            raise _InputError
        raw = path.read_bytes()
        if len(raw) > _MAX_INPUT_BYTES:
            raise _InputError
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except _InputError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        raise _InputError from None
    if type(value) is not dict or set(value) != {"request"}:
        raise _InputError
    return value["request"]


def _safe_input_path(value: object) -> Path:
    """Reject secret/raw/runtime locations before opening metadata."""
    if type(value) is not str or not value:
        raise _InputError
    path = Path(value)
    if not path.is_absolute():
        raise _InputError
    if any(part.lower() in _FORBIDDEN_PATH_PARTS for part in path.parts):
        raise _InputError
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        raise _InputError from None
    if any(part.lower() in _FORBIDDEN_PATH_PARTS for part in resolved.parts):
        raise _InputError
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if os.path.lexists(current) and current.is_symlink():
            raise _InputError
    return path


def _emit_failure(category: str, code: int) -> int:
    sys.stderr.write(json.dumps({"status": "failed", "category": category}, sort_keys=True) + "\n")
    return code


def _safe_result(result: object, gate: str) -> dict[str, object]:
    if not dataclasses.is_dataclass(result) or type(result).__module__ != "knowledgenexus.foundation.domain.models.foundation_gate":
        raise TypeError
    payload = dataclasses.asdict(result)
    if set(payload) - {
        "status", "evidence_kind", "kind_counts", "processed_count", "skipped_count", "failed_count",
        "deterministic_repeat", "source_unchanged", "no_silent_omission", "evidence_digest", "failure_reason", "media_scope",
        "profile_id", "target_pages", "observed_pages", "run_count", "stream_counts", "readback_valid",
        "relation_closed", "acl_closed", "sync_closed", "atomic_publish", "no_clobber", "sanitized_output",
        "transport", "rss_baseline_bytes", "rss_peak_bytes", "duration_milliseconds",
        "engine_id", "engine_version", "runtime_identity", "model_identity",
        "build_identity", "offline_only", "limits", "approved_at",
    }:
        raise TypeError
    payload["gate"] = gate
    payload["network_used"] = False
    payload["credentials_used"] = False
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        request = _request(args.gate, _load(args.input_path))
        if args.gate == "media":
            result = EvaluateBoundedMediaCorpusAcceptance().execute(request=request)
        elif args.gate == "ocr":
            result = EvaluateOcrEngineApproval().execute(request=request)
        else:
            result = EvaluateScaleGateEvidence().execute(request=request)
        output = _safe_result(result, args.gate)
        sys.stdout.write(json.dumps(output, sort_keys=True, allow_nan=False) + "\n")
        return EXIT_SUCCESS if output["status"] in {"approved", "complete", "pass"} else EXIT_GATE_FAILED
    except _ConfigurationError:
        return _emit_failure("configuration", EXIT_CONFIGURATION)
    except (_InputError, TypeError, ValueError):
        return _emit_failure("invalid_input", EXIT_INVALID_INPUT)
    except Exception:
        return _emit_failure("unexpected", EXIT_UNEXPECTED)


if __name__ == "__main__":
    raise SystemExit(main())
