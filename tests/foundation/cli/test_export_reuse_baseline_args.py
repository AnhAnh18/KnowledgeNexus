import json
from pathlib import Path

from knowledgenexus.foundation.cli import export_confluence_url_text_snapshot as mod


def test_reuse_args_write_the_unchanged_file_and_return_flags(tmp_path):
    state = tmp_path / ".state"
    state.mkdir()
    args = mod._reuse_baseline_capture_args(
        {
            "raw_root": "/base/.raw",
            "run_id": "abc",
            "versions": {"1": "v1", "2": "v2"},
        },
        state,
    )
    assert args[:2] == ["--reuse-baseline-raw-root", "/base/.raw"]
    assert "--reuse-baseline-run-id" in args and "abc" in args
    path_index = args.index("--reuse-unchanged-path") + 1
    written = json.loads(Path(args[path_index]).read_text(encoding="utf-8"))
    assert {row["page_id"]: row["source_version"] for row in written} == {"1": "v1", "2": "v2"}


def test_incomplete_reuse_input_yields_no_flags(tmp_path):
    state = tmp_path / ".state"
    state.mkdir()
    assert mod._reuse_baseline_capture_args({"raw_root": "", "run_id": "x", "versions": {"1": "v"}}, state) == []
    assert mod._reuse_baseline_capture_args({"raw_root": "/r", "run_id": "x", "versions": {}}, state) == []
    assert mod._reuse_baseline_capture_args({"raw_root": "/r", "run_id": "x"}, state) == []
