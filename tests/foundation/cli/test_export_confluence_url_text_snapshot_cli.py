from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli import export_confluence_url_text_snapshot as cli


_RUN_ID = "11111111-1111-4111-8111-111111111111"


def _operator_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tokenizer = tmp_path / "tokenizer"
    tokenizer.mkdir()
    (tokenizer / "tokenizer.json").write_text("{}", encoding="utf-8")
    chunking = tmp_path / "embedding_profile.yaml"
    reliability = tmp_path / "crawl_reliability_profile.yaml"
    chunking.write_text("profile: fixture\n", encoding="utf-8")
    reliability.write_text("profile: fixture\n", encoding="utf-8")
    monkeypatch.setattr(cli, "_DEFAULT_CHUNKING_PROFILE", chunking)
    monkeypatch.setattr(cli, "_DEFAULT_RELIABILITY_PROFILE", reliability)
    monkeypatch.setenv("CONFLUENCE_PAT", "fixture-secret")
    return tokenizer


class _PhaseMain:
    def __init__(
        self, *, fail_capture: bool = False,
        inventory_requires_poll: bool = False,
        capture_complete_after: int = 2,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.capture_calls = 0
        self.fail_capture = fail_capture
        self.inventory_requires_poll = inventory_requires_poll
        self.inventory_calls = 0
        self.capture_complete_after = capture_complete_after

    def __call__(self, argv: list[str] | None) -> int:
        assert type(argv) is list
        self.calls.append(tuple(argv))
        phase = argv[0]
        if phase == "inventory":
            self.inventory_calls += 1
            if self.inventory_requires_poll and self.inventory_calls == 1:
                payload = {
                    "status": "completed", "phase": "inventory",
                    "selected_pages": 0,
                }
            else:
                payload = {
                    "status": "complete", "phase": "inventory",
                    "selected_pages": 2, "run_id": _RUN_ID,
                }
        elif phase == "capture-pages":
            self.capture_calls += 1
            if self.fail_capture:
                payload = {
                    "status": "stopped", "phase": "capture-pages",
                    "captured": 1, "replayed": 0, "skipped": 0, "failed": 1,
                }
            else:
                payload = {
                    "status": (
                        "complete"
                        if self.capture_calls >= self.capture_complete_after
                        else "stopped"
                    ),
                    "phase": "capture-pages", "captured": 1,
                    "replayed": 0, "skipped": 0, "failed": 0,
                }
        elif phase in {"process-pages", "capture-drawio"}:
            payload = {"status": "complete", "phase": phase}
        elif phase == "export":
            output = Path(argv[argv.index("--output-dir") + 1])
            output.mkdir()
            (output / "documents.jsonl").write_text('{}\n', encoding="utf-8")
            (output / "chunks.jsonl").write_text('{}\n', encoding="utf-8")
            (output / "media_assets.jsonl").write_text("", encoding="utf-8")
            (output / "packet_summary.json").write_text(
                json.dumps(
                    {
                        "format_version": "confluence-subtree-indexing-packet-v1",
                        "acl_mode": "restricted_unresolved",
                        "document_count": 2, "chunk_count": 3,
                        "media_asset_count": 0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            payload = {
                "status": "complete", "phase": "export",
                "packet_published": True, "document_count": 2,
                "chunk_count": 3, "media_asset_count": 0,
            }
        else:
            raise AssertionError(phase)
        print(json.dumps(payload, separators=(",", ":")))
        return 0


@pytest.mark.parametrize(
    "value",
    (
        object(), None, "", "http://host/spaces/SPACE/pages/1/Title",
        "https://host/x/abc", "https://host/display/SPACE/Title",
        "https://host/spaces/space/pages/1/Title",
        "https://user:secret@host/spaces/SPACE/pages/1/Title",
        "https://host/pages/viewpage.action?pageId=1",
        "https://host/pages/viewpage.action?pageId=1&spaceKey=SPACE&unknown=1",
        "https://host/pages/viewpage.action?pageId=1&pageId=2&spaceKey=SPACE",
        "https://host/pages/viewpage.action?pageId=x&spaceKey=SPACE",
        "https://host/pages/viewpage.action?pageId=1&spaceKey=space",
        "https://host/x/",
        "https://host/x/AA",
    ),
)
def test_url_boundary_rejects_unsupported_and_malformed_values(value: object) -> None:
    with pytest.raises(cli.TextSnapshotOperatorError):
        cli.parse_canonical_page_url(value)


def test_canonical_url_resolves_context_base_scope_and_page() -> None:
    assert cli.parse_canonical_page_url(
        "https://Confluence.Example:443/wiki/spaces/SPACE/pages/12345/Page-Title"
    ) == ("https://confluence.example/wiki", "SPACE", "12345")


def test_viewpage_url_resolves_explicit_space_and_page_without_network() -> None:
    assert cli.parse_canonical_page_url(
        "https://confluence-mx.sec.samsung.net/pages/viewpage.action?"
        "pageId=938880621&spaceKey=SVMC&title=1.%2BS%2BPen%2BSDK"
    ) == ("https://confluence-mx.sec.samsung.net", "SVMC", "938880621")


def test_short_url_decodes_page_and_resolves_only_missing_space() -> None:
    calls: list[tuple[str, str]] = []

    def resolve(base_url: str, page_id: str) -> str:
        calls.append((base_url, page_id))
        return "SVMC"

    assert cli.parse_canonical_page_url(
        "https://confluence-mx.sec.samsung.net/x/bS72Nw",
        short_space_resolver=resolve,
    ) == ("https://confluence-mx.sec.samsung.net", "SVMC", "938880621")
    assert calls == [("https://confluence-mx.sec.samsung.net", "938880621")]


def test_short_url_without_resolver_fails_before_network() -> None:
    with pytest.raises(cli.TextSnapshotOperatorError) as raised:
        cli.parse_canonical_page_url("https://host/x/bS72Nw")
    assert raised.value.category == "url_requires_resolution"


def test_non_base64_short_url_uses_bounded_redirect_resolver() -> None:
    calls: list[tuple[str, str]] = []

    def resolve(base_url: str, token: str) -> tuple[str, str]:
        calls.append((base_url, token))
        return "SVMC", "217"

    assert cli.parse_canonical_page_url(
        "https://confluence-mx.sec.samsung.net/x/r1wAm",
        short_space_resolver=lambda _base, _page: pytest.fail("local decoder was used"),
        short_link_resolver=resolve,
    ) == ("https://confluence-mx.sec.samsung.net", "SVMC", "217")
    assert calls == [("https://confluence-mx.sec.samsung.net", "r1wAm")]


class _RedirectOpener:
    def __init__(self, location: str, *, status: int = 302) -> None:
        self.location = location
        self.status = status
        self.requests: list[object] = []

    def open(self, request, timeout):
        self.requests.append(request)
        assert timeout == 30.0
        raise urllib.error.HTTPError(
            request.full_url, self.status, "redirect",
            {"Location": self.location}, None,
        )


def test_redirect_reader_accepts_only_same_origin_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONFLUENCE_PAT", "fixture-secret")
    opener = _RedirectOpener(
        "/pages/viewpage.action?pageId=217&spaceKey=SVMC"
    )

    location = cli._read_short_redirect_location(
        "https://confluence.example", "r1wAm", opener=opener,
    )

    assert location == (
        "https://confluence.example/pages/viewpage.action?"
        "pageId=217&spaceKey=SVMC"
    )
    assert opener.requests[0].get_header("Authorization") == "Bearer fixture-secret"


@pytest.mark.parametrize(
    "location",
    (
        "http://confluence.example/pages/viewpage.action?pageId=217&spaceKey=SVMC",
        "https://evil.example/pages/viewpage.action?pageId=217&spaceKey=SVMC",
        "https://user:secret@confluence.example/pages/viewpage.action?pageId=217&spaceKey=SVMC",
        "https://confluence.example/pages/viewpage.action?pageId=217&spaceKey=SVMC#fragment",
    ),
)
def test_redirect_reader_rejects_unsafe_locations(
    monkeypatch: pytest.MonkeyPatch, location: str,
) -> None:
    monkeypatch.setenv("CONFLUENCE_PAT", "fixture-secret")
    with pytest.raises(cli.TextSnapshotOperatorError):
        cli._read_short_redirect_location(
            "https://confluence.example", "r1wAm",
            opener=_RedirectOpener(location),
        )


def test_viewpage_redirect_without_space_uses_metadata_resolver() -> None:
    assert cli.parse_canonical_page_url(
        "https://host/pages/viewpage.action?pageId=217",
        short_space_resolver=lambda base, page: (
            "SVMC" if (base, page) == ("https://host", "217") else "wrong"
        ),
    ) == ("https://host", "SVMC", "217")


@pytest.mark.parametrize("resolved", (None, object(), "", "space", "A-B"))
def test_short_url_rejects_malformed_resolver_results(resolved: object) -> None:
    with pytest.raises(cli.TextSnapshotOperatorError) as raised:
        cli.parse_canonical_page_url(
            "https://host/x/bS72Nw",
            short_space_resolver=lambda _base, _page: resolved,
        )
    assert raised.value.category == "short_url_resolution"


def test_run_composes_bounded_phases_and_publishes_latest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer = _operator_files(tmp_path, monkeypatch)
    phases = _PhaseMain()
    output = tmp_path / "operator-output"

    result = cli.run(
        url="https://confluence.example/spaces/SPACE/pages/12345/Root",
        output_root=str(output), tokenizer_assets_dir=str(tokenizer),
        max_pages=200, phase_main=phases,
    )

    assert result == {
        "status": "complete", "already_published": False,
        "document_count": 2, "chunk_count": 3, "media_asset_count": 0,
        "acl_mode": "restricted_unresolved",
    }
    assert [call[0] for call in phases.calls] == [
        "inventory", "capture-pages", "capture-pages",
        "process-pages", "capture-drawio", "export",
    ]
    assert (output / "LATEST.txt").read_text(encoding="ascii") == f"confluence-{_RUN_ID}\n"
    version = output / "versions" / f"confluence-{_RUN_ID}"
    assert {path.name for path in version.iterdir()} == cli._PACKET_FILES

    replay = cli.run(
        url="https://confluence.example/spaces/SPACE/pages/12345/Root",
        output_root=str(output), tokenizer_assets_dir=str(tokenizer),
        max_pages=200, phase_main=lambda _argv: pytest.fail("published replay called a phase"),
    )
    assert replay == {
        "status": "complete", "already_published": True,
        "acl_mode": "restricted_unresolved",
    }


def test_failed_capture_stops_before_processing_and_remains_resumable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer = _operator_files(tmp_path, monkeypatch)
    phases = _PhaseMain(fail_capture=True)
    output = tmp_path / "operator-output"

    with pytest.raises(cli.TextSnapshotOperatorError) as raised:
        cli.run(
            url="https://confluence.example/spaces/SPACE/pages/12345/Root",
            output_root=str(output), tokenizer_assets_dir=str(tokenizer),
            max_pages=200, phase_main=phases,
        )

    assert raised.value.category == "capture_incomplete"
    assert [call[0] for call in phases.calls] == ["inventory", "capture-pages"]
    context = json.loads((output / cli._CONTEXT_FILE).read_text(encoding="utf-8"))
    assert context["run_id"] == _RUN_ID
    assert not (output / "LATEST.txt").exists()


def test_explicit_best_effort_mode_publishes_partial_packet_without_downstream_phases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer = _operator_files(tmp_path, monkeypatch)
    phases = _PhaseMain()

    class _Exporter:
        def __init__(self, *, validator: object) -> None:
            assert callable(getattr(validator, "validate_record", None))

        def publish(self, *, output_dir: Path, documents, chunks, media_assets, summary):
            assert tuple(media_assets) == ()
            output_dir.mkdir()
            (output_dir / "documents.jsonl").write_text("{}\n", encoding="utf-8")
            (output_dir / "chunks.jsonl").write_text("{}\n", encoding="utf-8")
            (output_dir / "media_assets.jsonl").write_text("", encoding="utf-8")
            payload = dict(summary)
            payload.update({
                "format_version": "confluence-subtree-indexing-packet-v1",
                "document_count": len(tuple(documents)),
                "chunk_count": len(tuple(chunks)),
                "media_asset_count": 0,
                "acl_mode": "restricted_unresolved",
            })
            (output_dir / "packet_summary.json").write_text(
                json.dumps(payload) + "\n", encoding="utf-8",
            )
            return {
                "document_count": payload["document_count"],
                "chunk_count": payload["chunk_count"],
                "media_asset_count": 0,
            }

    monkeypatch.setattr(cli, "SubtreePacketExporter", _Exporter)
    partial = cli._PartialProcessingResult(
        documents=({"document_id": "document-1"},),
        chunks=({"chunk_id": "chunk-1"},),
        requested_pages=2,
        succeeded_pages=1,
        failure_categories=(("unsplittable_table_row", 1),),
    )
    output = tmp_path / "operator-output"
    result = cli.run(
        url="https://confluence.example/spaces/SPACE/pages/12345/Root",
        output_root=str(output), tokenizer_assets_dir=str(tokenizer),
        max_pages=200, allow_partial_processing=True,
        phase_main=phases, partial_processor=lambda **_kwargs: partial,
    )

    assert result["status"] == "partial"
    assert result["requested_pages"] == 2
    assert result["succeeded_pages"] == 1
    assert result["failed_pages"] == 1
    assert result["failure_categories"] == {"unsplittable_table_row": 1}
    assert [call[0] for call in phases.calls] == [
        "inventory", "capture-pages", "capture-pages",
    ]
    summary = json.loads(
        (output / "versions" / f"confluence-{_RUN_ID}" / "packet_summary.json")
        .read_text(encoding="utf-8")
    )
    assert summary["processing_status"] == "partial"
    assert summary["drawio_status"] == "not_captured_in_best_effort_mode"

    replay = cli.run(
        url="https://confluence.example/spaces/SPACE/pages/12345/Root",
        output_root=str(output), tokenizer_assets_dir=str(tokenizer),
        max_pages=200, phase_main=lambda _argv: pytest.fail("replay called a phase"),
    )
    assert replay["status"] == "partial"

    summary["failed_pages"] = 2
    (output / "versions" / f"confluence-{_RUN_ID}" / "packet_summary.json").write_text(
        json.dumps(summary) + "\n", encoding="utf-8",
    )
    with pytest.raises(cli.TextSnapshotOperatorError) as raised:
        cli.run(
            url="https://confluence.example/spaces/SPACE/pages/12345/Root",
            output_root=str(output), tokenizer_assets_dir=str(tokenizer),
            max_pages=200, phase_main=lambda _argv: pytest.fail("called a phase"),
        )
    assert raised.value.category == "publication"


@pytest.mark.parametrize(
    "kwargs",
    (
        {"documents": (), "chunks": (), "requested_pages": 2,
         "succeeded_pages": 0, "failure_categories": (("failed", 2),)},
        {"documents": ({},), "chunks": ({},), "requested_pages": 2,
         "succeeded_pages": 1, "failure_categories": (("failed", 2),)},
        {"documents": ({},), "chunks": ({},), "requested_pages": 2,
         "succeeded_pages": 1, "failure_categories": (("z", 1), ("a", 1))},
    ),
)
def test_partial_result_rejects_impossible_cross_field_states(kwargs) -> None:
    with pytest.raises((TypeError, ValueError)):
        cli._PartialProcessingResult(**kwargs)


def test_capture_allows_one_terminal_confirmation_after_final_committed_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer = _operator_files(tmp_path, monkeypatch)
    phases = _PhaseMain(capture_complete_after=4)

    result = cli.run(
        url="https://confluence.example/spaces/SPACE/pages/12345/Root",
        output_root=str(tmp_path / "operator-output"),
        tokenizer_assets_dir=str(tokenizer), max_pages=300,
        phase_main=phases,
    )

    assert result["status"] == "complete"
    capture_calls = [call for call in phases.calls if call[0] == "capture-pages"]
    assert len(capture_calls) == 4


def test_new_inventory_polls_committed_snapshot_once_before_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer = _operator_files(tmp_path, monkeypatch)
    phases = _PhaseMain(inventory_requires_poll=True)

    result = cli.run(
        url="https://confluence.example/spaces/SPACE/pages/12345/Root",
        output_root=str(tmp_path / "operator-output"),
        tokenizer_assets_dir=str(tokenizer), max_pages=200,
        phase_main=phases,
    )

    assert result["status"] == "complete"
    inventory_calls = [call for call in phases.calls if call[0] == "inventory"]
    assert len(inventory_calls) == 2
    assert "--resume-unique" not in inventory_calls[0]
    assert "--resume-unique" in inventory_calls[1]


def test_existing_unowned_output_directory_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer = _operator_files(tmp_path, monkeypatch)
    output = tmp_path / "operator-output"
    output.mkdir()
    (output / "owner.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(cli.TextSnapshotOperatorError) as raised:
        cli.run(
            url="https://confluence.example/spaces/SPACE/pages/12345/Root",
            output_root=str(output), tokenizer_assets_dir=str(tokenizer),
            phase_main=lambda _argv: pytest.fail("phase should not run"),
        )

    assert raised.value.category == "output_not_empty"
    assert (output / "owner.txt").read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    "payload",
    (
        object(), None, {},
        {"status": "complete", "phase": "wrong", "count": 1},
        {"status": "unknown", "phase": "inventory", "count": 1},
        {"status": "complete", "phase": "inventory", "count": True},
        {"status": "complete", "phase": "inventory", "count": -1},
    ),
)
def test_phase_result_cross_field_validation_rejects_impossible_states(payload: object) -> None:
    with pytest.raises(cli.TextSnapshotOperatorError):
        cli._require_phase_result(
            payload, phase="inventory", statuses=frozenset({"complete"}),
            counters=("count",),
        )


@pytest.mark.parametrize("value", (object(), None, "0", 0, -1, True, 5_001))
def test_page_bound_rejects_wrong_runtime_types_and_out_of_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: object,
) -> None:
    tokenizer = _operator_files(tmp_path, monkeypatch)
    with pytest.raises(cli.TextSnapshotOperatorError) as raised:
        cli.run(
            url="https://confluence.example/spaces/SPACE/pages/12345/Root",
            output_root=str(tmp_path / "out"), tokenizer_assets_dir=str(tokenizer),
            max_pages=value,
        )
    assert raised.value.category == "page_bound"


@pytest.mark.parametrize("value", (object(), None, "true", 1, 0, (), {}))
def test_partial_mode_rejects_wrong_runtime_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: object,
) -> None:
    tokenizer = _operator_files(tmp_path, monkeypatch)
    with pytest.raises(cli.TextSnapshotOperatorError) as raised:
        cli.run(
            url="https://confluence.example/spaces/SPACE/pages/12345/Root",
            output_root=str(tmp_path / "out"), tokenizer_assets_dir=str(tokenizer),
            allow_partial_processing=value,
        )
    assert raised.value.category == "partial_mode"


def test_partial_processor_is_forbidden_without_explicit_partial_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer = _operator_files(tmp_path, monkeypatch)
    with pytest.raises(cli.TextSnapshotOperatorError) as raised:
        cli.run(
            url="https://confluence.example/spaces/SPACE/pages/12345/Root",
            output_root=str(tmp_path / "out"), tokenizer_assets_dir=str(tokenizer),
            partial_processor=lambda **_kwargs: object(),
        )
    assert raised.value.category == "partial_mode"


@pytest.mark.parametrize(
    "phase_main",
    (
        lambda _argv: None,
        lambda _argv: print("[]") or 0,
        lambda _argv: print('{"status":"complete"}\n{}') or 0,
        lambda _argv: print('{"status":null}') or 0,
    ),
)
def test_phase_boundary_fails_closed_on_malformed_public_results(phase_main) -> None:
    with pytest.raises(cli.TextSnapshotOperatorError):
        cli._invoke_phase(["inventory"], phase_main=phase_main)


def test_main_failure_is_sanitized(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) != 0
    captured = capsys.readouterr()
    assert "usage:" in captured.err
    assert "Traceback" not in captured.err


def test_powershell_entrypoint_exposes_two_required_operator_parameters() -> None:
    text = (_REPO_ROOT / "scripts" / "run-confluence-text-demo.ps1").read_text(encoding="utf-8")
    assert "[string]$Url" in text
    assert "[string]$OutputRoot" in text
    assert "CONFLUENCE_PAT" in text
    assert "KN_TOKENIZER_ASSETS_DIR" in text
    assert 'Join-Path $repositoryRoot "src"' in text
    assert "$env:PYTHONPATH" in text
    assert '"--url", $Url' in text
    assert '"--output-root", $OutputRoot' in text
    assert "[switch]$AllowPartialProcessing" in text
    assert '"--allow-partial-processing"' in text
    assert "--pat" not in text.lower()


def test_demo_runbook_documents_partial_resume_and_url_identity() -> None:
    text = (_REPO_ROOT / "docs" / "runbooks" / "CONFLUENCE_TEXT_DEMO.md").read_text(
        encoding="utf-8"
    )
    for required in (
        "-AllowPartialProcessing",
        "processing_status: partial",
        "restricted:unresolved",
        "documents.jsonl",
        "chunks.jsonl",
        "LATEST.txt",
        "(base_url, space_key, root_page_id, max_pages)",
        "context_binding",
        "url_shape",
        "unsplittable_table_row",
    ):
        assert required in text


_REPO_ROOT = Path(__file__).resolve().parents[3]
