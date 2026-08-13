from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli import confluence_subtree_corpus


_ROOT = Path(__file__).resolve().parents[3]
_RUNBOOKS = _ROOT / "docs" / "runbooks"


def test_w5_a_runbooks_are_portable_and_separate_live_phases() -> None:
    names = (
        "W5_A_REAL_INPUT_ACCEPTANCE.md",
        "W5_B_ROOT1_FULL_SNAPSHOT.md",
        "W5_C_SECOND_SYNC_DELTA.md",
    )
    for name in names:
        text = (_RUNBOOKS / name).read_text(encoding="utf-8")
        assert "credentials" in text.lower()
        assert "sanitized" in text.lower()
        assert "owner" in text.lower()
    assert "does not authorize" in (
        _RUNBOOKS / "W5_A_REAL_INPUT_ACCEPTANCE.md"
    ).read_text(encoding="utf-8")
    b_text = (_RUNBOOKS / "W5_B_ROOT1_FULL_SNAPSHOT.md").read_text(encoding="utf-8")
    c_text = (_RUNBOOKS / "W5_C_SECOND_SYNC_DELTA.md").read_text(encoding="utf-8")
    assert "--export-mode delta" in c_text
    assert "--phase" not in b_text + c_text
    assert "confluence_subtree_corpus inventory @common" in b_text
    assert "--resume-unique | ConvertFrom-Json" in b_text + c_text
    assert "inventory completion readback failed" in b_text + c_text
    assert "confluence_subtree_corpus capture-delta-inventory @common" in c_text
    assert '"--raw-root", "<ABS-RAW-ROOT>"' in b_text
    assert '"--raw-root", "<ABS-SECOND-RAW-ROOT>"' in c_text
    assert "$run = $inventory.run_id" in b_text + c_text
    assert "--run-id $run" in b_text + c_text
    assert "--resume-run-id $run" not in b_text + c_text
    assert '--raw-generation-root "<ABS-RAW-ROOT>"' in b_text
    assert '--raw-generation-root "<ABS-SECOND-RAW-ROOT>"' in c_text
    assert "COMMAND 1" in b_text + c_text
    assert "COMMAND 2" in b_text + c_text
    assert "--stop-after-batches 2" in b_text + c_text
    assert "must interrupt" not in (b_text + c_text).lower()
    assert "do not use Ctrl+C" in b_text + c_text
    assert "<ABS-DATASET-ROOT-A>" in b_text
    assert "<ABS-DATASET-ROOT-B>" in b_text
    assert "runtime roots must be absent" in b_text
    assert "-RecoveryOnly" in b_text
    assert "production strict readback" in b_text
    assert "and `LATEST.txt` must be absent" in b_text
    assert "delta dataset root must already exist as an empty plain directory" in c_text
    assert "--jira-relation-profile" in b_text + c_text


def test_w5_media_scope_is_registered_in_the_active_acceptance_contract() -> None:
    text = (
        _ROOT / "contracts" / "foundation" / "CRAWL_ACCEPTANCE_SPEC.md"
    ).read_text(encoding="utf-8")
    assert "### 13.1 W5 bounded media acceptance scope" in text
    assert "all_media" in text
    assert "drawio_only" in text
    assert "does not claim PDF, image, chart, OCR, audio, or video acceptance" in text


def test_w5_a_sanitized_templates_are_valid_pending_envelopes() -> None:
    for name in (
        "W5_B_SANITIZED_EVIDENCE_TEMPLATE.json",
        "W5_C_SANITIZED_EVIDENCE_TEMPLATE.json",
    ):
        payload = json.loads((_RUNBOOKS / name).read_text(encoding="utf-8"))
        assert payload["status"] == "pending_external_input"
        assert payload["authorization_consumed"] is False
        assert payload["failure_category"] is None
        serialized = json.dumps(payload).lower()
        for forbidden in ("http://", "https://", "password", "page_id"):
            assert forbidden not in serialized


def test_w5_root1_runbook_locks_post_inventory_failure_vocabulary() -> None:
    text = (_ROOT / "scripts" / "run-w5-root1-live.ps1").read_text(
        encoding="utf-8"
    )
    expected = set(confluence_subtree_corpus._ACTIVATION_FAILURE_CATEGORIES.values())
    expected.update({
        "inventory_stream",
        "inventory_selection_invalid",
        "selection_publication",
    })
    match = re.search(
        r"\$script:PostInventoryFailureCategories\s*=\s*@\((.*?)\)",
        text,
        flags=re.DOTALL,
    )
    assert match is not None
    assert set(re.findall(r'"([^"]+)"', match.group(1))) == expected

    function_start = text.index("function Assert-PhaseResultEnvelope")
    function_end = text.index("function Assert-InventoryResult", function_start)
    boundary = text[function_start:function_end]
    assert boundary.index("$Value.PSObject.Properties.Name") < boundary.index(
        "$Value.status"
    )
    assert "Fail-Gate $Stage" in boundary

    inventory_start = text.index("function Assert-InventoryResult")
    capture_start = text.index("function Assert-CaptureResult", inventory_start)
    processing_start = text.index("function Assert-ProcessingResult", capture_start)
    assert "Assert-PhaseResultEnvelope" in text[inventory_start:capture_start]
    assert "Assert-PhaseResultEnvelope" in text[capture_start:processing_start]


def test_w5_root1_runbook_executes_adversarial_phase_envelope_checks(
    tmp_path: Path,
) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("PowerShell is required to execute the Windows runbook validator")
    text = (_ROOT / "scripts" / "run-w5-root1-live.ps1").read_text(
        encoding="utf-8"
    )

    assignment_start = text.index("$script:PostInventoryFailureCategories")
    assignment_end = text.index("\n)", assignment_start) + 2
    fail_start = text.index("function Fail-Gate")
    fail_end = text.index("function Get-StrictTopLevelJsonPropertyNames", fail_start)
    exact_start = text.index("function Assert-ExactObject")
    exact_end = text.index("function Full-Path", exact_start)
    phase_start = text.index("function Assert-PhaseResultEnvelope")
    phase_end = text.index("function Assert-ProcessingResult", phase_start)

    production_definitions = "\n".join((
        '$ErrorActionPreference = "Stop"',
        '$script:FailureStage = "probe"',
        text[assignment_start:assignment_end],
        text[fail_start:fail_end],
        text[exact_start:exact_end],
        text[phase_start:phase_end],
    ))
    probe = production_definitions + r'''
function Expect-StageFailure([object]$Value, [string]$Expected) {
    $script:FailureStage = "unset"
    $threw = $false
    try {
        Assert-PhaseResultEnvelope $Value @("status", "phase") "probe"
    }
    catch {
        $threw = $true
    }
    if (-not $threw -or $script:FailureStage -ne $Expected) {
        throw "unexpected validation outcome"
    }
}

Expect-StageFailure $null "probe"
Expect-StageFailure @() "probe"
Expect-StageFailure "scalar" "probe"
Expect-StageFailure ([pscustomobject]@{status="failed"}) "probe"
Expect-StageFailure ([pscustomobject]@{
    status="failed"; failure_category="inventory_stream"; extra=$true
}) "probe"
Expect-StageFailure ([pscustomobject]@{
    status="complete"; failure_category="inventory_stream"
}) "probe"
Expect-StageFailure ([pscustomobject]@{
    status="failed"; failure_category="unknown"
}) "probe"
Expect-StageFailure ([pscustomobject]@{
    status="failed"; failure_category="inventory_stream"
}) "inventory_stream"

$script:FailureStage = "unset"
try {
    Assert-CaptureResult ([pscustomobject]@{
        status="failed"; failure_category="selection_publication"
    }) "complete" "capture_resume"
}
catch {}
if ($script:FailureStage -ne "selection_publication") {
    throw "capture failure category was discarded"
}

Assert-PhaseResultEnvelope ([pscustomobject]@{
    status="complete"; phase="inventory"
}) @("status", "phase") "probe"
'''
    probe_path = tmp_path / "runbook-validator-probe.ps1"
    probe_path.write_text(probe, encoding="utf-8")
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-File", str(probe_path)],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
