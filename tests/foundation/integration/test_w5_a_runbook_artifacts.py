from __future__ import annotations

import json
from pathlib import Path


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
    assert "<ABS-DATASET-ROOT-A>" in b_text
    assert "<ABS-DATASET-ROOT-B>" in b_text
    assert "--jira-relation-profile" in b_text + c_text


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
