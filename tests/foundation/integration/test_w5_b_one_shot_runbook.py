from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "run-w5-root1-live.ps1"
TEMPLATE = ROOT / "docs" / "runbooks" / "W5_B_ONE_SHOT_CONFIG.template.json"


def test_one_shot_config_is_private_input_template_without_credentials() -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert payload["format_version"] == "w5-b-root1-one-shot-v1"
    assert payload["owner_authorized"] is False
    assert payload["transfer_equivalent"] is False
    assert payload["max_pages"] == 5000
    serialized = json.dumps(payload).lower()
    assert "confluence_pat" not in serialized
    assert "password" not in serialized
    assert "http://" not in serialized and "https://" not in serialized


def test_one_shot_script_locks_phase_order_resume_and_text_first_scope() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    phases = (
        '(@("inventory") + $common) $true "inventory_start"',
        '(@("inventory") + $common + @("--resume-unique")) $true "inventory_readback"',
        '"--stop-after-batches", "2"',
        '$true "capture_resume"',
        '$false "process_pages"',
        '$true "capture_drawio"',
        '$false $Stage',
    )
    positions = [text.index(fragment) for fragment in phases]
    assert positions == sorted(positions)
    assert '"--media-policy", "required"' in text
    assert "OCR" not in text
    assert "PDF" not in text
    assert "Ctrl+C" not in text
    assert "--stop-after-batches" in text
    assert "[switch]$PreflightOnly" in text
    assert '"status":"preflight_complete"' in text
    assert "CONFLUENCE_PAT" in text
    assert 'if (-not $Live)' in text
    assert "Remove-Item Env:CONFLUENCE_PAT" in text


def test_one_shot_script_requires_atomic_snapshot_shape_and_sanitized_evidence() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for name in (
        "documents.jsonl",
        "chunks.jsonl",
        "relations.jsonl",
        "acl.jsonl",
        "media_assets.jsonl",
        "symbols.jsonl",
        "sync_state.jsonl",
        "tombstones.jsonl",
        "manifest.json",
        "quality_report.md",
        "LATEST.txt",
    ):
        assert name in text
    assert "Get-TreeDigest" in text
    assert "deterministic_export" in text
    assert "raw_state_mutation" in text
    assert "w5-b-sanitized-summary.json" in text
    assert "run_id =" not in text
    assert "dataset_version =" not in text
