from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "run-w5-root1-live.ps1"
TEMPLATE = ROOT / "docs" / "runbooks" / "W5_B_ONE_SHOT_CONFIG.template.json"


def test_one_shot_config_is_private_input_template_without_credentials() -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert payload["format_version"] == "w5-b-root1-operator-v2"
    assert payload["owner_authorized"] is False
    assert payload["reviewed_code_confirmed"] is False
    assert payload["max_pages"] == 5000
    assert set(payload) == {
        "format_version",
        "owner_authorized",
        "reviewed_code_confirmed",
        "python_executable",
        "output_root",
        "max_pages",
        "tokenizer_assets_dir",
        "space_key",
        "root_page_id",
    }
    serialized = json.dumps(payload).lower()
    assert "confluence_pat" not in serialized
    assert "password" not in serialized
    assert "http://" not in serialized and "https://" not in serialized
    assert "git_commit" not in serialized
    assert "expected_execution_head" not in serialized


def test_simple_profile_derives_git_and_approved_profiles_from_checkout() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'Split-Path -Parent $PSScriptRoot' in text
    assert 'rev-parse HEAD' in text
    assert 'symbolic-ref --quiet --short HEAD' in text
    assert 'Join-Path $script:RepoRoot "config/foundation/embedding_profile.yaml"' in text
    assert 'Join-Path $outputRoot "state"' in text
    assert 'Join-Path $outputRoot "snapshot-a"' in text
    assert 'Join-Path $outputRoot "snapshot-b"' in text
    assert 'Join-Path $outputRoot "evidence"' in text


def test_one_shot_script_locks_phase_order_resume_and_text_first_scope() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    phases = (
        '(@("inventory") + $common) $true "inventory_start"',
        '(@("inventory") + $common + @("--resume-unique")) $true "inventory_readback"',
        '"--stop-after-batches", "2"',
        '$true "capture_resume"',
        '$false "process_pages"',
        '$true "capture_drawio"',
        '$result = Invoke-ExporterModuleJson $arguments $Stage',
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
    assert "Wait-LiveProcessBoundary" in text
    assert "max_child_working_set_bytes" in text
    assert "child_time_budget" in text
    assert "[switch]$RecoveryOnly" in text
    assert '"exporter_invocations":0' in text
    assert '"PYTHONDONTWRITEBYTECODE"] = "1"' in text
    assert '"-p", "no:cacheprovider"' in text
    for required_suite in (
        "test_export_m10_snapshot_cli.py",
        "test_m10_operator_cli_e2e.py",
        "test_export_m10_snapshot.py",
        "test_delta_snapshot_reader.py",
        "test_snapshot_readback.py",
    ):
        assert required_suite in text


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
    sanitized_summary = text[
        text.index("function Write-SanitizedSummary") : text.index("\ntry {", text.index("function Write-SanitizedSummary"))
    ]
    assert "run_id =" not in sanitized_summary
    assert "dataset_version =" not in sanitized_summary


def test_recovery_branch_uses_only_the_read_only_strict_verifier() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index('    if ($RecoveryOnly) {\n        $stateDir')
    end = text.index("\n    $testArguments = @(", start)
    recovery = text[start:end]
    assert "Get-TreeDigest" in recovery
    assert 'Invoke-ModuleJson "knowledgenexus.foundation.cli.verify_w5_snapshot_pair"' in recovery
    assert "Export-Once" not in recovery
    assert '"exporter_invocations":0' in recovery
    assert '"read_only_verifier_invocations":1' in recovery


def test_failure_evidence_reports_actual_exporter_invocation_count(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    source = SCRIPT.read_text(encoding="utf-8")
    helpers = source[: source.index("\ntry {")]
    probe = helpers + r'''
function Invoke-ModuleJson {
  param([string]$Module,[string[]]$Arguments,[bool]$Live,[string]$Stage)
  throw [System.InvalidOperationException]::new("forced export failure")
}
try { [void](Invoke-ExporterModuleJson @("--probe") "export_a") } catch { }
$script:FailureStage = "export_a"
$payload = New-FailurePayload $true
if ($payload.exporter_invocations -ne 1 -or $payload.failure_category -ne "export_a") { exit 2 }
Write-Output ($payload | ConvertTo-Json -Compress)
'''
    target = tmp_path / "exporter-count-probe.ps1"
    target.write_text(probe, encoding="utf-8")

    result = subprocess.run(
        [powershell, "-NoProfile", "-File", str(target), "-OperatorConfig", "unused"],
        cwd=ROOT, text=True, capture_output=True, check=False, timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["exporter_invocations"] == 1


def _run_config(config_path: Path) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    return subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-OperatorConfig",
            str(config_path),
            "-PreflightOnly",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize("malformed_value", ['"true"', "1"])
def test_one_shot_rejects_coercible_authorization_values(
    tmp_path: Path, malformed_value: str
) -> None:
    text = TEMPLATE.read_text(encoding="utf-8").replace(
        '"owner_authorized": false',
        f'"owner_authorized": {malformed_value}',
    )
    target = tmp_path / "private-config.json"
    target.write_text(text, encoding="utf-8")

    result = _run_config(target)

    assert result.returncode == 1
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload == {
        "all_gates_passed": False,
        "authorization_consumed": False,
        "exporter_invocations": 0,
        "failure_category": "configuration",
        "status": "failed",
    }


def test_one_shot_rejects_duplicate_config_keys(tmp_path: Path) -> None:
    text = TEMPLATE.read_text(encoding="utf-8").replace(
        '"owner_authorized": false,',
        '"owner_authorized": false,\n  "owner_authorized": true,',
    )
    target = tmp_path / "private-config.json"
    target.write_text(text, encoding="utf-8")

    result = _run_config(target)

    assert result.returncode == 1
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["failure_category"] == "configuration"
    assert payload["authorization_consumed"] is False


@pytest.mark.parametrize(
    "payload",
    (
        None,
        [],
        {},
        {"format_version": None},
        {"format_version": "unknown"},
    ),
)
def test_one_shot_rejects_malformed_top_level_profiles(
    tmp_path: Path, payload: object
) -> None:
    target = tmp_path / "private-config.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    result = _run_config(target)

    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout)["failure_category"] == "configuration"


def test_simple_profile_reaches_offline_preflight_without_manual_git_fields(
    tmp_path: Path,
) -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    git = shutil.which("git")
    if powershell is None or git is None:
        pytest.skip("PowerShell or Git is unavailable")
    repo = tmp_path / "repo" / "KnowledgeNexus"
    scripts = repo / "scripts"
    contracts = repo / "contracts" / "foundation"
    scripts.mkdir(parents=True)
    contracts.mkdir(parents=True)
    shutil.copy2(SCRIPT, scripts / SCRIPT.name)
    (contracts / "crawl_reliability_profile.yaml").write_text(
        "minimum_request_interval_seconds: 3.0\n"
        "max_total_requests_per_run: 50000\n"
        "minimum_free_disk_reserve_bytes: 1\n",
        encoding="utf-8",
    )
    (contracts / "embedding_profile.yaml").write_text("profile: test\n", encoding="utf-8")
    (contracts / "jira_relation_profile.yaml").write_text("profile: test\n", encoding="utf-8")
    subprocess.run([git, "init", "-q", str(repo)], check=True)
    subprocess.run([git, "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run([git, "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run([git, "-C", str(repo), "add", "."], check=True)
    subprocess.run([git, "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    tokenizer = tmp_path / "tokenizer"
    tokenizer.mkdir()
    config = {
        "format_version": "w5-b-root1-operator-v2",
        "owner_authorized": False,
        "reviewed_code_confirmed": True,
        "python_executable": sys.executable,
        "output_root": str(tmp_path / "fresh-output"),
        "max_pages": 201,
        "tokenizer_assets_dir": str(tokenizer),
        "space_key": "SPACE",
        "root_page_id": "1000",
    }
    config_path = tmp_path / "private-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(scripts / SCRIPT.name),
            "-OperatorConfig",
            str(config_path),
            "-PreflightOnly",
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout)["failure_category"] == "offline_preflight_tests"
    assert not (tmp_path / "fresh-output").exists()


def test_child_result_validators_reject_coercible_and_extra_state(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    source = SCRIPT.read_text(encoding="utf-8")
    helpers = source[: source.index("\ntry {")]
    probe = helpers + r'''
$rejected = 0
$cases = @(
  @("inventory", '{"status":"complete","phase":"inventory","selected_pages":"201","run_id":"123e4567-e89b-42d3-a456-426614174000"}'),
  @("inventory", '[{"status":"complete","phase":"inventory","selected_pages":201,"run_id":"123e4567-e89b-42d3-a456-426614174000"}]'),
  @("capture", '{"status":"stopped","phase":"capture-pages","captured":"200","replayed":0,"skipped":0,"failed":0}'),
  @("capture", '{"status":"stopped","phase":"capture-pages","captured":199,"replayed":0,"skipped":1,"failed":0}'),
  @("capture", '{"status":"complete","phase":"capture-pages","captured":1,"replayed":199,"skipped":0,"failed":0}'),
  @("processing", '{"status":"complete","phase":"process-pages","page_count":10,"document_count":9,"chunk_count":20}'),
  @("drawio", '{"status":"complete","phase":"capture-drawio","drawio_references_observed":2,"drawio_references_resolved":1,"drawio_assets_failed":0}'),
  @("export", '{"status":"success","dataset_version":"v1","counts":{"documents":1,"chunks":1,"relations":0,"acl":1,"media_assets":0,"symbols":0,"sync_state":1,"tombstones":0},"network_used":"false","credentials_used":false}'),
  @("export", '{"status":"success","dataset_version":"v20260812-000000-000000Z","counts":{"documents":2,"chunks":1,"relations":0,"acl":1,"media_assets":0,"symbols":1,"sync_state":0,"tombstones":1},"network_used":false,"credentials_used":false}'),
  @("inventory", '{"status":"complete","phase":"inventory","selected_pages":201,"run_id":"123e4567-e89b-42d3-a456-426614174000","extra":true}')
)
foreach ($case in $cases) {
  try {
    $value = $case[1] | ConvertFrom-Json
    if ($case[0] -eq "inventory") { Assert-InventoryResult $value "probe" }
    elseif ($case[0] -eq "capture") { Assert-CaptureResult $value "stopped" "probe" }
    elseif ($case[0] -eq "processing") { Assert-ProcessingResult $value "probe" }
    elseif ($case[0] -eq "drawio") { Assert-DrawioResult $value "probe" }
    else { Assert-ExportResult $value "probe" }
  } catch { $rejected += 1 }
}
try {
  [void]@(Get-StrictTopLevelJsonPropertyNames '{"status":"complete","status":"failed"}')
} catch { $rejected += 1 }
try {
  [void]@(Get-StrictTopLevelJsonPropertyNames '{"status":"success","counts":{"documents":1,"documents":2}}')
} catch { $rejected += 1 }
try {
  [void]@(Get-StrictTopLevelJsonPropertyNames '{"status":"success","counts":{"documents":1,"docu\u006dents":2}}')
} catch { $rejected += 1 }
if ($rejected -ne ($cases.Count + 3)) { exit 2 }
Write-Output "ALL_REJECTED"
'''
    target = tmp_path / "validator-probe.ps1"
    target.write_text(probe, encoding="utf-8")

    result = subprocess.run(
        [powershell, "-NoProfile", "-File", str(target), "-OperatorConfig", "unused"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ALL_REJECTED"


def _operator_tree_digest(roots: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for root_index, root in enumerate(sorted(roots, key=lambda item: str(item).lower())):
        digest.update(f"root-{root_index}\0".encode())
        files = sorted(
            (path for path in root.rglob("*") if path.is_file()),
            key=lambda item: str(item).lower(),
        )
        for path in files:
            relative = str(path)[len(str(root).rstrip("\\/")) :].lstrip("\\/")
            digest.update((relative + "\0").encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_recovery_only_audits_existing_snapshots_without_exporter_invocation(
    tmp_path: Path,
) -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    git = shutil.which("git")
    if powershell is None or git is None:
        pytest.skip("PowerShell or Git is unavailable")
    repo = tmp_path / "repo"
    contracts = repo / "contracts" / "foundation"
    scripts = repo / "scripts"
    contracts.mkdir(parents=True)
    scripts.mkdir(parents=True)
    shutil.copytree(ROOT / "src", repo / "src")
    shutil.copy2(SCRIPT, scripts / SCRIPT.name)
    shutil.copytree(ROOT / "contracts" / "foundation" / "schemas", contracts / "schemas")
    (contracts / "crawl_reliability_profile.yaml").write_text(
        "minimum_request_interval_seconds: 3.0\n"
        "max_total_requests_per_run: 50000\n"
        "minimum_free_disk_reserve_bytes: 8589934592\n",
        encoding="utf-8",
    )
    (contracts / "embedding_profile.yaml").write_text("profile: test\n", encoding="utf-8")
    (contracts / "jira_relation_profile.yaml").write_text("profile: test\n", encoding="utf-8")
    subprocess.run([git, "init", "-q", str(repo)], check=True)
    subprocess.run([git, "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run([git, "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run([git, "-C", str(repo), "add", "."], check=True)
    subprocess.run([git, "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    head = subprocess.check_output([git, "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

    state, raw, dataset_a, dataset_b, evidence = (
        tmp_path / name for name in ("state", "raw", "dataset-a", "dataset-b", "evidence")
    )
    for path in (state, raw, dataset_a, dataset_b, evidence):
        path.mkdir()
    (state / "state.bin").write_bytes(b"state")
    (raw / "raw.bin").write_bytes(b"raw")
    golden = ROOT / "tests" / "fixtures" / "foundation" / "golden_full_snapshot"
    shutil.rmtree(dataset_a)
    shutil.rmtree(dataset_b)
    shutil.copytree(golden, dataset_a)
    shutil.copytree(golden, dataset_b)
    private_state = {
        "format_version": "w5-b-private-export-state-v1",
        "run_id": "123e4567-e89b-42d3-a456-426614174000",
        "raw_state_digest_before_export": _operator_tree_digest((raw, state)),
        "original_live_process_invocations": 5,
        "profile_verified": True,
        "tokenizer_verified": True,
    }
    (evidence / "w5-b-private-export-state.json").write_text(
        json.dumps(private_state), encoding="utf-8"
    )
    config = {
        "format_version": "w5-b-root1-one-shot-v1",
        "owner_authorized": False,
        "transfer_equivalent": True,
        "expected_execution_head": head,
        "repo_root": str(repo),
        "python_executable": sys.executable,
        "state_dir": str(state),
        "max_pages": 5000,
        "raw_root": str(raw),
        "reliability_profile_path": str(contracts / "crawl_reliability_profile.yaml"),
        "chunking_profile_path": str(contracts / "embedding_profile.yaml"),
        "jira_relation_profile_path": str(contracts / "jira_relation_profile.yaml"),
        "tokenizer_assets_dir": str(tmp_path / "not-used-tokenizer"),
        "space_key": "SPACE",
        "root_page_id": "1000",
        "dataset_root_a": str(dataset_a),
        "dataset_root_b": str(dataset_b),
        "evidence_dir": str(evidence),
        "git_repository": "fixture/repo",
        "git_branch": "main",
        "git_commit": "a" * 40,
        "live_phase_timeout_seconds": 60,
        "offline_phase_timeout_seconds": 60,
        "max_child_working_set_bytes": 1073741824,
    }
    config_path = tmp_path / "private-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-OperatorConfig",
            str(config_path),
            "-RecoveryOnly",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "all_gates_passed": True,
        "exporter_invocations": 0,
        "read_only_verifier_invocations": 1,
        "status": "recovery_complete",
    }
    summary = json.loads(
        (evidence / "w5-b-sanitized-recovery-summary.json").read_text(encoding="utf-8")
    )
    assert summary["operator_mode"] == "recovery"
    assert summary["authorization_consumed"] is True
    assert summary["recovery_exporter_invocations"] == 0

    simple_root = tmp_path / "simple-runtime"
    simple_root.mkdir()
    for source, name in (
        (state, "state"),
        (raw, "raw"),
        (dataset_a, "snapshot-a"),
        (dataset_b, "snapshot-b"),
        (evidence, "evidence"),
    ):
        shutil.copytree(source, simple_root / name)
    simple_config = {
        "format_version": "w5-b-root1-operator-v2",
        "owner_authorized": False,
        "reviewed_code_confirmed": True,
        "python_executable": sys.executable,
        "output_root": str(simple_root),
        "max_pages": 5000,
        "tokenizer_assets_dir": str(tmp_path / "not-used-tokenizer"),
        "space_key": "SPACE",
        "root_page_id": "1000",
    }
    simple_config_path = tmp_path / "simple-private-config.json"
    simple_config_path.write_text(json.dumps(simple_config), encoding="utf-8")

    simple_result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(scripts / SCRIPT.name),
            "-OperatorConfig",
            str(simple_config_path),
            "-RecoveryOnly",
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert simple_result.returncode == 0, simple_result.stdout + simple_result.stderr
    assert json.loads(simple_result.stdout)["status"] == "recovery_complete"
