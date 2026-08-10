from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli import evaluate_foundation_gates as cli


_DIGEST = "a" * 64
_KINDS = ("chart_screenshot", "digital_pdf", "drawio", "image", "image_only_pdf")
_STREAMS = (
    ["acl", 10], ["chunks", 20], ["documents", 10], ["media_assets", 5],
    ["relations", 4], ["symbols", 2], ["sync_state", 13], ["tombstones", 0],
)


def _media_run() -> dict[str, object]:
    outcomes = [
        {
            "media_id": f"confluence:attachment:{number}",
            "kind": kind,
            "status": "processed",
            "result_digest": hashlib.sha256(str(number).encode()).hexdigest(),
        }
        for number, kind in zip(range(1000, 1005), _KINDS)
    ]
    return {
        "outcomes": outcomes,
        "expected_media_ids": [item["media_id"] for item in outcomes],
        "source_digest_before": _DIGEST,
        "source_digest_after": _DIGEST,
        "write_digest_before": "b" * 64,
        "write_digest_after": "b" * 64,
    }


def _readback() -> dict[str, object]:
    return {
        "dataset_version": "v20260808-120000-000001Z",
        "content_digest": _DIGEST,
        "observed_pages": 10000,
        "stream_counts": _STREAMS,
        "readback_valid": True,
        "relation_closed": True,
        "acl_closed": True,
        "sync_closed": True,
        "atomic_publish": True,
        "no_clobber": True,
        "sanitized_output": True,
        "transport": "production",
        "rss_baseline_bytes": 100,
        "rss_peak_bytes": 200,
        "duration_milliseconds": 300,
    }


def _write(tmp_path: Path, value: object) -> Path:
    path = tmp_path / "gate.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_media_cli_emits_only_sanitized_aggregate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, {"request": {
        "first_run": _media_run(),
        "second_run": _media_run(),
        "evidence_kind": "sanitized_real_capture",
        "real_capture_attested": True,
        "transport": "production",
    }})

    assert cli.main(["--gate", "media", "--input", str(path)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    result = json.loads(captured.out)
    assert result["status"] == "complete"
    assert result["gate"] == "media"
    assert result["network_used"] is False
    assert result["credentials_used"] is False
    assert "outcomes" not in captured.out


def test_scale_cli_accepts_repeat_readback(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(tmp_path, {"request": {
        "profile_id": "m7-crawl-scale-acceptance-v2",
        "target_pages": 10000,
        "first_readback": _readback(),
        "second_readback": _readback(),
        "evidence_kind": "sanitized_real_capture",
    }})

    assert cli.main(["--gate", "scale", "--input", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"


def _ocr_approval() -> dict[str, object]:
    return {
        "status": "approved",
        "engine_id": "tesseract",
        "engine_version": "5.3.0",
        "runtime_identity": "runtime-20260808",
        "model_identity": "eng-traineddata",
        "build_identity": "build-20260808",
        "offline_only": True,
        "limits": {
            "max_input_bytes": 32 * 1024 * 1024,
            "max_raster_bytes": 64 * 1024 * 1024,
            "max_output_bytes": 8 * 1024 * 1024,
            "max_images": 100,
            "max_seconds": 120.0,
            "min_confidence": 0.0,
            "min_text_bytes": 1,
        },
        "evidence_kind": "sanitized_real_capture",
        "evidence_digest": "d" * 64,
        "approved_at": "2026-08-08T12:00:00Z",
    }


def test_ocr_cli_accepts_complete_sanitized_approval(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, {"request": _ocr_approval()})
    assert cli.main(["--gate", "ocr", "--input", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["gate"] == "ocr"
    assert result["status"] == "approved"
    assert result["network_used"] is False
    assert "evidence_digest" in result


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "approved", "engine_id": "guess"},
        {**_ocr_approval(), "limits": {"max_images": 0}},
        {**_ocr_approval(), "evidence_kind": "synthetic_fixture"},
    ],
)
def test_ocr_cli_rejects_incomplete_or_impossible_approval(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], payload: dict[str, object]
) -> None:
    path = _write(tmp_path, {"request": payload})
    assert cli.main(["--gate", "ocr", "--input", str(path)]) == cli.EXIT_INVALID_INPUT
    assert json.loads(capsys.readouterr().err) == {"category": "invalid_input", "status": "failed"}


def test_failed_gate_emits_sanitized_result_and_fails_automation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _readback()
    second = _readback()
    second["content_digest"] = "c" * 64
    path = _write(tmp_path, {"request": {
        "profile_id": "m7-crawl-scale-acceptance-v2",
        "target_pages": 10000,
        "first_readback": first,
        "second_readback": second,
        "evidence_kind": "synthetic_fixture",
    }})

    assert cli.main(["--gate", "scale", "--input", str(path)]) == cli.EXIT_GATE_FAILED
    captured = capsys.readouterr()
    assert captured.err == ""
    result = json.loads(captured.out)
    assert result["status"] == "failed"
    assert result["failure_reason"] == "nondeterministic_repeat"


def test_cli_rejects_duplicate_json_keys(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"request": {"request": {}, "request": {}}}', encoding="utf-8")

    assert cli.main(["--gate", "media", "--input", str(path)]) == cli.EXIT_INVALID_INPUT
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {"category": "invalid_input", "status": "failed"}


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"request": {"first_run": object()}},
        {"request": {"first_run": _media_run(), "second_run": _media_run(), "evidence_kind": "bad", "extra": 1}},
        {"request": {"first_run": _media_run(), "second_run": _media_run(), "evidence_kind": "synthetic_fixture", "raw": "secret"}},
    ],
)
def test_cli_rejects_wrong_types_missing_fields_and_raw_extra_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], payload: object
) -> None:
    # object() is not JSON-serializable, so represent that malformed case as
    # a JSON scalar while retaining the same boundary test.
    if payload is None:
        value = None
    elif isinstance(payload, dict) and isinstance(payload.get("request"), dict):
        value = payload
        if isinstance(value["request"], dict) and isinstance(value["request"].get("first_run"), object) and not isinstance(value["request"].get("first_run"), (dict, list, str, int, float, bool, type(None))):
            value = {"request": {"first_run": 1}}
    else:
        value = payload
    path = _write(tmp_path, value)

    assert cli.main(["--gate", "media", "--input", str(path)]) == cli.EXIT_INVALID_INPUT
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {"category": "invalid_input", "status": "failed"}
    assert str(path) not in captured.err
    assert captured.out == ""


def test_cli_rejects_oversized_input_without_echoing_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "large.json"
    path.write_bytes(b"{" + b" " * cli._MAX_INPUT_BYTES + b"}")

    assert cli.main(["--gate", "media", "--input", str(path)]) == cli.EXIT_INVALID_INPUT
    captured = capsys.readouterr()
    assert str(path) not in captured.err


@pytest.mark.parametrize("dirname", [".local_ai", "evidence", "raw", "runtime"])
def test_cli_rejects_forbidden_input_locations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], dirname: str
) -> None:
    forbidden = tmp_path / dirname
    forbidden.mkdir()
    path = forbidden / "gate.json"
    path.write_text("{}", encoding="utf-8")

    assert cli.main(["--gate", "media", "--input", str(path)]) == cli.EXIT_INVALID_INPUT
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {"category": "invalid_input", "status": "failed"}
    assert captured.out == ""


def test_cli_rejects_symlinked_input_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")

    assert cli.main(["--gate", "media", "--input", str(link)]) == cli.EXIT_INVALID_INPUT
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {"category": "invalid_input", "status": "failed"}


def test_cli_rejects_configuration_without_echoing_argument(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--gate", "media"]) == cli.EXIT_CONFIGURATION
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {"category": "configuration", "status": "failed"}
    assert "--gate" not in captured.err
