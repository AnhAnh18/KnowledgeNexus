from __future__ import annotations

import copy
import csv
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceDataCenterPayloadError,
    ConfluenceHttpError,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    confluence_http_transport as transport_module,
)
from knowledgenexus.foundation.infrastructure.exporters import (
    confluence_inventory_report_writer as writer_module,
)
from knowledgenexus.foundation.cli import confluence_inventory_smoke as smoke


FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "foundation"
    / "confluence_data_center"
)
ROOT_PAGE_ID = "1000"
DIRECT_CHILD_ID = "1001"
NESTED_CHILD_ID = "1002"
TERMINAL_CHILD_ID = "1003"
SPACE_KEY = "SPACE"
SOURCE_ID = "smoke-fixture-source"
BASE_URL = "https://fixture.invalid/confluence"
PAT = "fixture-secret-token"
ROOT_PATH = f"/rest/api/content/{ROOT_PAGE_ID}"
SEARCH_PATH = "/rest/api/search"
_SYNTHETIC_ID_MAP = {
    "GLOBAL_PAGE": "900",
    "SELECTED_PAGE": ROOT_PAGE_ID,
    "DIRECT_CHILD": DIRECT_CHILD_ID,
    "NESTED_CHILD": NESTED_CHILD_ID,
    "TERMINAL_CHILD": TERMINAL_CHILD_ID,
}


@pytest.fixture(autouse=True)
def _forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prove no test can reach the network through the real transport."""

    def explode(*args: object, **kwargs: object) -> object:
        raise AssertionError("smoke tests must not open a network connection")

    monkeypatch.setattr(transport_module.urllib.request, "build_opener", explode)
    monkeypatch.setattr(transport_module.urllib.request, "urlopen", explode)


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(smoke.BASE_URL_ENV, BASE_URL)
    monkeypatch.setenv(smoke.PAT_ENV, PAT)


class FakeTransport:
    instances: list[FakeTransport] = []

    def __init__(self, *, base_url: str, personal_access_token: str) -> None:
        self.base_url = base_url
        self.personal_access_token = personal_access_token
        self.requests: list[dict[str, Any]] = []
        FakeTransport.instances.append(self)

    def get_json(
        self,
        *,
        path: str,
        query: Mapping[str, str],
    ) -> Mapping[str, object]:
        self.requests.append({"path": path, "query": dict(query)})
        return _serve_fixtures(path, dict(query))


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[str, dict[str, str]], Mapping[str, object]] | None = None,
) -> None:
    FakeTransport.instances = []

    class _Transport(FakeTransport):
        def get_json(
            self,
            *,
            path: str,
            query: Mapping[str, str],
        ) -> Mapping[str, object]:
            self.requests.append({"path": path, "query": dict(query)})
            served = handler or _serve_fixtures
            return served(path, dict(query))

    monkeypatch.setattr(smoke, "UrllibConfluenceHttpTransport", _Transport)


def _argv(output_dir: Path, **overrides: Any) -> list[str]:
    argv = [
        "--source-id",
        overrides.get("source_id", SOURCE_ID),
        "--space-key",
        overrides.get("space_key", SPACE_KEY),
        "--root-page-id",
        overrides.get("root_page_id", ROOT_PAGE_ID),
        "--page-size",
        str(overrides.get("page_size", 2)),
        "--max-search-pages",
        str(overrides.get("max_search_pages", 10)),
        "--output-dir",
        str(output_dir),
    ]
    for page_id in overrides.get("exclude", ()):
        argv.extend(["--exclude-subtree-page-id", page_id])
    return argv


def test_successful_run_writes_exactly_three_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_transport(monkeypatch)

    assert smoke.main(_argv(tmp_path)) == 0

    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "inventory_report.csv",
        "m5c_smoke_summary.json",
        "pages_inventory.jsonl",
    ]


def test_run_composes_production_transport_adapter_and_use_case(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_transport(monkeypatch)

    assert smoke.main(_argv(tmp_path)) == 0

    transport = FakeTransport.instances[0]
    assert transport.base_url == BASE_URL
    assert transport.personal_access_token == PAT
    # Exact approved M5B-2 request shape, produced by the production adapter.
    assert transport.requests[0] == {
        "path": ROOT_PATH,
        "query": {"expand": "space,version"},
    }
    assert transport.requests[1]["path"] == SEARCH_PATH
    assert transport.requests[1]["query"]["cql"] == (
        f'space="{SPACE_KEY}" and ancestor={ROOT_PAGE_ID} and type=page'
    )
    assert transport.requests[1]["query"]["limit"] == "2"


def test_reports_are_written_by_the_m5a_writer_not_hand_serialized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_transport(monkeypatch)

    assert smoke.main(_argv(tmp_path)) == 0

    with (tmp_path / "inventory_report.csv").open(encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh))
    assert tuple(header) == smoke.CSV_COLUMNS

    records = [
        json.loads(line)
        for line in (tmp_path / "pages_inventory.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert [record["page_id"] for record in records] == [
        ROOT_PAGE_ID,
        DIRECT_CHILD_ID,
        TERMINAL_CHILD_ID,
        NESTED_CHILD_ID,
    ]


def test_summary_counts_depth_and_flags_are_correct(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_transport(monkeypatch)

    assert smoke.main(_argv(tmp_path, exclude=(DIRECT_CHILD_ID,))) == 0

    summary = _summary(tmp_path)
    assert summary["status"] == "passed"
    assert summary["total_items"] == 4
    assert summary["root_items"] == 1
    assert summary["included_items"] == 2
    assert summary["excluded_subtree_items"] == 2
    assert summary["maximum_relative_depth"] == 2
    assert summary["attachment_count_all_unknown"] is True
    assert summary["root_labels_requested"] is False
    assert summary["root_labels_interpretation"] == "unknown_not_requested"
    assert summary["page_size"] == 2
    assert summary["max_search_pages"] == 10


def test_summary_row_counts_match_the_reopened_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_transport(monkeypatch)

    assert smoke.main(_argv(tmp_path)) == 0

    summary = _summary(tmp_path)
    jsonl_lines = [
        line
        for line in (tmp_path / "pages_inventory.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    with (tmp_path / "inventory_report.csv").open(encoding="utf-8", newline="") as fh:
        csv_rows = list(csv.reader(fh))[1:]
    assert summary["pages_inventory_jsonl_records"] == len(jsonl_lines) == 4
    assert summary["inventory_report_csv_data_rows"] == len(csv_rows) == 4


def test_csv_row_count_is_logical_not_physical_lines(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # A real title may contain a newline; the CSV then has more physical lines
    # than logical records.
    def handler(path: str, query: dict[str, str]) -> Mapping[str, object]:
        payload = _serve_fixtures(path, query)
        if path == SEARCH_PATH and query["start"] == "0":
            payload["results"][0]["content"]["title"] = (
                'Multi\nline, "quoted" title'
            )
        return payload

    _install_transport(monkeypatch, handler)

    assert smoke.main(_argv(tmp_path)) == 0

    csv_text = (tmp_path / "inventory_report.csv").read_text(encoding="utf-8")
    summary = _summary(tmp_path)
    assert len(csv_text.splitlines()) > summary["inventory_report_csv_data_rows"] + 1
    assert summary["inventory_report_csv_data_rows"] == summary["total_items"] == 4


def test_summary_hashes_match_the_published_report_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_transport(monkeypatch)

    assert smoke.main(_argv(tmp_path)) == 0

    summary = _summary(tmp_path)
    assert summary["pages_inventory_jsonl_sha256"] == _sha256(
        tmp_path / "pages_inventory.jsonl"
    )
    assert summary["inventory_report_csv_sha256"] == _sha256(
        tmp_path / "inventory_report.csv"
    )


def test_summary_carries_no_source_scope_connection_or_secret_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_transport(monkeypatch)

    assert smoke.main(_argv(tmp_path, exclude=(DIRECT_CHILD_ID,))) == 0

    summary_text = (tmp_path / "m5c_smoke_summary.json").read_text(encoding="utf-8")
    stdout = capsys.readouterr().out
    for haystack in (summary_text, stdout):
        for forbidden in (
            SOURCE_ID,
            SPACE_KEY,
            BASE_URL,
            "fixture.invalid",
            PAT,
            "Fixture Root Page",
            "Fixture Nested Child",
        ):
            assert forbidden not in haystack
    # Structural proof: only allowlisted keys, no free-text identifier field.
    assert set(json.loads(summary_text)) == {
        *smoke._SUMMARY_FIXED_FIELDS,
        *smoke._SUMMARY_INT_FIELDS,
        *smoke._SUMMARY_HASH_FIELDS,
    }


def test_summary_is_deterministic_strict_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_transport(monkeypatch)

    assert smoke.main(_argv(tmp_path)) == 0

    raw = (tmp_path / "m5c_smoke_summary.json").read_bytes()
    assert raw.endswith(b"\n")
    text = raw.decode("utf-8")
    assert json.dumps(
        json.loads(text),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n" == text


@pytest.mark.parametrize("missing", (smoke.BASE_URL_ENV, smoke.PAT_ENV))
def test_missing_credential_env_fails_as_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    missing: str,
) -> None:
    _install_transport(monkeypatch)
    monkeypatch.delenv(missing)

    assert smoke.main(_argv(tmp_path)) == 2

    assert json.loads(capsys.readouterr().err) == {
        "status": "failed",
        "category": "configuration",
        "cleanup_incomplete": False,
    }
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("flag", ("--pat", "--personal-access-token", "--token"))
def test_pat_cannot_be_supplied_through_the_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    flag: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_transport(monkeypatch)

    assert smoke.main([*_argv(tmp_path), flag, "REVIEW_SENTINEL_SECRET"]) == 2

    # argparse echoes the offending arguments before raising; a mistyped
    # `--pat <token>` must never reach the terminal or a shell log.
    captured = capsys.readouterr()
    for stream in (captured.out, captured.err):
        assert "REVIEW_SENTINEL_SECRET" not in stream
    assert json.loads(captured.err)["category"] == "configuration"
    assert list(tmp_path.iterdir()) == []


def test_invalid_cli_error_never_echoes_argv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_transport(monkeypatch)

    sentinel_root_id = "7777777777"

    assert (
        smoke.main(
            [
                *_argv(tmp_path, root_page_id=sentinel_root_id),
                "--not-a-real-flag",
                BASE_URL,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    for stream in (captured.out, captured.err):
        for forbidden in (
            BASE_URL,
            "fixture.invalid",
            sentinel_root_id,
            "--not-a-real-flag",
        ):
            assert forbidden not in stream


def test_help_still_works_and_returns_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert smoke.main(["--help"]) == 0

    assert "confluence-inventory-smoke" in capsys.readouterr().out


def test_output_dir_inside_the_repository_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_transport(monkeypatch)

    assert smoke.main(_argv(smoke._REPO_ROOT / "tests")) == 3

    assert json.loads(capsys.readouterr().err)["category"] == "output_directory"


def test_repository_root_itself_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_transport(monkeypatch)

    assert smoke.main(_argv(smoke._REPO_ROOT)) == 3


def test_missing_output_dir_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_transport(monkeypatch)

    assert smoke.main(_argv(tmp_path / "absent")) == 3


def test_non_directory_output_path_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_transport(monkeypatch)
    target = tmp_path / "a-file"
    target.write_text("", encoding="utf-8")

    assert smoke.main(_argv(target)) == 3


def test_non_empty_output_dir_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_transport(monkeypatch)
    (tmp_path / "pre-existing.txt").write_text("", encoding="utf-8")

    assert smoke.main(_argv(tmp_path)) == 3
    assert sorted(path.name for path in tmp_path.iterdir()) == ["pre-existing.txt"]


def test_failed_inventory_writes_no_summary_and_leaves_no_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(path: str, query: dict[str, str]) -> Mapping[str, object]:
        if path == ROOT_PATH:
            return _root_payload()
        raise ConfluenceHttpError("Confluence GET returned HTTP status 503")

    _install_transport(monkeypatch, handler)

    assert smoke.main(_argv(tmp_path)) == 5

    assert list(tmp_path.iterdir()) == []
    assert json.loads(capsys.readouterr().err)["status"] == "failed"


@pytest.mark.parametrize(
    ("message", "expected_code"),
    (
        ("Confluence GET returned HTTP status 401", 5),
        ("Confluence GET failed", 4),
        ("Confluence GET returned a non-JSON content type", 5),
        ("Confluence GET returned malformed JSON", 6),
    ),
)
def test_transport_failures_map_to_stable_categories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    message: str,
    expected_code: int,
) -> None:
    def handler(path: str, query: dict[str, str]) -> Mapping[str, object]:
        raise ConfluenceHttpError(message)

    _install_transport(monkeypatch, handler)

    assert smoke.main(_argv(tmp_path)) == expected_code


def test_response_contract_failure_maps_to_its_category(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def handler(path: str, query: dict[str, str]) -> Mapping[str, object]:
        return _root_payload(space_key="OUTSIDE")

    _install_transport(monkeypatch, handler)

    assert smoke.main(_argv(tmp_path)) == 6


def test_pagination_budget_exhaustion_maps_to_its_category(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def handler(path: str, query: dict[str, str]) -> Mapping[str, object]:
        if path == ROOT_PATH:
            return _root_payload()
        payload = _search_payload("search_page_start_0.json")
        payload["start"] = int(query["start"])
        payload["totalSize"] = payload["start"] + payload["size"] + 1
        return payload

    _install_transport(monkeypatch, handler)

    assert smoke.main(_argv(tmp_path, max_search_pages=2)) == 7


def test_failure_output_discloses_no_connection_or_secret_detail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(path: str, query: dict[str, str]) -> Mapping[str, object]:
        raise ConfluenceHttpError(
            f"Confluence GET to {BASE_URL} with {PAT} returned HTTP status 401"
        )

    _install_transport(monkeypatch, handler)

    assert smoke.main(_argv(tmp_path)) == 5

    captured = capsys.readouterr()
    for stream in (captured.out, captured.err):
        for forbidden in (PAT, BASE_URL, "fixture.invalid", SPACE_KEY, ROOT_PAGE_ID):
            assert forbidden not in stream


def test_unexpected_error_is_sanitized_and_categorized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(path: str, query: dict[str, str]) -> Mapping[str, object]:
        raise RuntimeError(f"leaky failure carrying {PAT}")

    _install_transport(monkeypatch, handler)

    assert smoke.main(_argv(tmp_path)) == 1

    captured = capsys.readouterr()
    assert json.loads(captured.err)["category"] == "unexpected"
    assert PAT not in captured.err


def test_attachment_count_invariant_is_enforced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_execute = smoke.BuildConfluenceInventory.execute

    def enriched(self: Any, *, config: Any) -> Any:
        # Simulate a future attachment enrichment reaching the M5C boundary,
        # which M5B must never perform.
        return tuple(
            replace(item, attachment_count=3)
            for item in real_execute(self, config=config)
        )

    _install_transport(monkeypatch)
    monkeypatch.setattr(smoke.BuildConfluenceInventory, "execute", enriched)

    assert smoke.main(_argv(tmp_path)) == 9
    assert list(tmp_path.iterdir()) == []


def test_report_verification_failure_removes_only_runner_owned_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_transport(monkeypatch)
    monkeypatch.setattr(smoke, "_count_jsonl_records", lambda path: 999)

    assert smoke.main(_argv(tmp_path)) == 9
    assert list(tmp_path.iterdir()) == []


def test_failure_after_summary_publication_removes_the_passed_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The summary is fully published, then a later step fails. A complete
    # `status: passed` summary must not survive, because the runbook makes its
    # presence the proof that the run passed.
    real_check = smoke._require_exact_output_tree
    calls: list[set[str]] = []

    def fail_after_publish(output_dir: Path, expected: set[str]) -> None:
        calls.append(expected)
        if len(calls) == 2:
            assert (output_dir / "m5c_smoke_summary.json").is_file()
            raise smoke.SmokeFailure(smoke.CATEGORY_REPORT_VERIFICATION)
        real_check(output_dir, expected)

    _install_transport(monkeypatch)
    monkeypatch.setattr(smoke, "_require_exact_output_tree", fail_after_publish)

    assert smoke.main(_argv(tmp_path)) == 9

    assert list(tmp_path.iterdir()) == []
    assert json.loads(capsys.readouterr().err) == {
        "status": "failed",
        "category": "report_verification",
        "cleanup_incomplete": False,
    }


def test_summary_publish_failure_leaves_no_temp_behind(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # The temp exists before the link is attempted; a failing link must still
    # leave nothing, and must not register a target this runner never created.
    #
    # `os` is a shared module object, so refuse only the summary's own link and
    # delegate the writer's report links: otherwise the run fails at the writer
    # and never reaches the publisher this test is about.
    real_link = smoke.os.link
    published: list[int] = []
    real_publish = smoke._publish_summary

    def refuse_summary_link(src: Any, dst: Any) -> None:
        if Path(dst).name == "m5c_smoke_summary.json":
            raise OSError("link refused")
        real_link(src, dst)

    def counting_publish(**kwargs: Any) -> None:
        published.append(1)
        return real_publish(**kwargs)

    _install_transport(monkeypatch)
    monkeypatch.setattr(smoke, "_publish_summary", counting_publish)
    monkeypatch.setattr(smoke.os, "link", refuse_summary_link)

    assert smoke.main(_argv(tmp_path)) == 9

    assert published == [1], "the publisher under test must actually run"
    assert list(tmp_path.iterdir()) == []


def test_cleanup_never_removes_a_concurrent_creators_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Another process wins the race between the empty check and the write. The
    # writer refuses to clobber it; this runner must not delete it either.
    real_write = smoke.ConfluenceInventoryReportWriter.write
    foreign = "owned by another process"

    def racing_write(*, output_dir: Path, items: Any) -> int:
        (output_dir / "pages_inventory.jsonl").write_text(foreign, encoding="utf-8")
        return real_write(output_dir=output_dir, items=items)

    _install_transport(monkeypatch)
    monkeypatch.setattr(
        smoke.ConfluenceInventoryReportWriter, "write", staticmethod(racing_write)
    )

    assert smoke.main(_argv(tmp_path)) == 8

    survivor = tmp_path / "pages_inventory.jsonl"
    assert survivor.is_file()
    assert survivor.read_text(encoding="utf-8") == foreign


def test_summary_publish_never_clobbers_a_concurrent_creators_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Another process creates the summary name after verification but before
    # publication. It must survive untouched and the run must fail closed.
    real_render = smoke._render_summary
    foreign = "owned by another process"

    def render_then_race(summary: Any) -> bytes:
        (tmp_path / "m5c_smoke_summary.json").write_text(foreign, encoding="utf-8")
        return real_render(summary)

    _install_transport(monkeypatch)
    monkeypatch.setattr(smoke, "_render_summary", render_then_race)

    assert smoke.main(_argv(tmp_path)) == 9

    survivor = tmp_path / "m5c_smoke_summary.json"
    assert survivor.read_text(encoding="utf-8") == foreign
    assert not any(path.name.endswith(".tmp") for path in tmp_path.iterdir())


def test_summary_temp_name_is_unique_per_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # A fixed temp name would let two concurrent runners clobber each other.
    observed: list[str] = []
    real_link = smoke.os.link

    def record_then_link(src: Any, dst: Any) -> None:
        observed.append(Path(src).name)
        real_link(src, dst)

    _install_transport(monkeypatch)
    monkeypatch.setattr(smoke.os, "link", record_then_link)
    assert smoke.main(_argv(tmp_path)) == 0

    second = tmp_path.parent / "second"
    second.mkdir()
    _install_transport(monkeypatch)
    assert smoke.main(_argv(second)) == 0

    # `os` is a shared module object, so this also records the writer's links.
    summary_temps = [
        name for name in observed if name.startswith(".m5c_smoke_summary.json.")
    ]
    assert len(summary_temps) == 2
    assert summary_temps[0] != summary_temps[1]
    assert all(name.endswith(".tmp") for name in summary_temps)


def test_leftover_writer_temp_files_fail_closed_without_passed_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # The M5A writer swallows failures when removing its own temp files; those
    # temps hold a second copy of real inventory metadata.
    monkeypatch.setattr(writer_module, "_remove_owned_file", lambda path: None)
    _install_transport(monkeypatch)

    assert smoke.main(_argv(tmp_path)) == 9

    names = sorted(path.name for path in tmp_path.iterdir())
    assert "m5c_smoke_summary.json" not in names
    # Writer-owned temporaries are left for the operator, never deleted here.
    assert any(name.endswith(".tmp") for name in names)


def test_unexpected_output_entry_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_write = smoke.ConfluenceInventoryReportWriter.write

    def write_then_litter(*, output_dir: Path, items: Any) -> int:
        written = real_write(output_dir=output_dir, items=items)
        (output_dir / "unexpected.txt").write_text("", encoding="utf-8")
        return written

    _install_transport(monkeypatch)
    monkeypatch.setattr(
        smoke.ConfluenceInventoryReportWriter, "write", staticmethod(write_then_litter)
    )

    assert smoke.main(_argv(tmp_path)) == 9
    assert "m5c_smoke_summary.json" not in [p.name for p in tmp_path.iterdir()]


def test_page_size_and_budget_must_be_positive_integers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_transport(monkeypatch)

    assert smoke.main(_argv(tmp_path, page_size=0)) == 2
    assert smoke.main(_argv(tmp_path, max_search_pages=0)) == 2
    assert smoke.main(_argv(tmp_path, page_size="two")) == 2
    assert list(tmp_path.iterdir()) == []


def _summary(output_dir: Path) -> dict[str, Any]:
    return json.loads((output_dir / "m5c_smoke_summary.json").read_text("utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _serve_fixtures(path: str, query: dict[str, str]) -> Mapping[str, object]:
    if path == ROOT_PATH:
        return _root_payload()
    if path == SEARCH_PATH and query["start"] == "0":
        return _search_payload("search_page_start_0.json")
    if path == SEARCH_PATH and query["start"] == "2":
        return _search_payload("search_page_terminal.json")
    raise AssertionError("unexpected fixture request")


def _root_payload(
    *,
    page_id: str = ROOT_PAGE_ID,
    space_key: str = SPACE_KEY,
) -> dict[str, Any]:
    payload = _load_fixture("root_page_response.json")
    payload["id"] = page_id
    payload["space"] = {"key": space_key}
    return payload


def _search_payload(name: str) -> dict[str, Any]:
    return _replace_fixture_ids(_load_fixture(name))


def _replace_fixture_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _replace_fixture_ids(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_fixture_ids(item) for item in value]
    if isinstance(value, str):
        return _SYNTHETIC_ID_MAP.get(value, value)
    return value


def _load_fixture(name: str) -> dict[str, Any]:
    return copy.deepcopy(json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8")))
