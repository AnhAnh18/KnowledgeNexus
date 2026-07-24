from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli import collect_confluence_page_observations as cli
from knowledgenexus.foundation.application.use_cases.collect_confluence_page_observations import (
    PageObservationCollectionResult,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceHttpResponse,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    confluence_http_transport as transport_module,
)
from knowledgenexus.foundation.infrastructure.sidecars import (
    RestrictionSidecarPublicationError,
    RestrictionSidecarSerializationError,
    RestrictionSidecarTargetError,
)

PAGE_ID = "1000"
BASE_URL = "https://fixture.invalid/confluence"
PAT = "fixture-secret-token"
SECRET_FILENAME = "private-synthetic-file.pdf"
SECRET_PRINCIPAL = "private-synthetic-user"


@pytest.fixture(autouse=True)
def _forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> object:
        raise AssertionError("offline tests must never open a network connection")

    monkeypatch.setattr(transport_module.urllib.request, "build_opener", explode)
    monkeypatch.setattr(transport_module.urllib.request, "urlopen", explode)


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cli.BASE_URL_ENV, BASE_URL)
    monkeypatch.setenv(cli.PAT_ENV, PAT)


class FakeTransport:
    last: FakeTransport | None = None

    def __init__(self, *, base_url: str, personal_access_token: str, **kwargs: object):
        self.base_url = base_url
        self.pat = personal_access_token
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        FakeTransport.last = self

    def get_response_bytes(
        self, *, path: str, query: Mapping[str, str]
    ) -> ConfluenceHttpResponse:
        self.calls.append(("restriction", path, dict(query)))
        body = json.dumps(
            {
                "operation": "view",
                "restrictions": {
                    "user": {"results": [{"username": SECRET_PRINCIPAL}]},
                    "group": {"results": []},
                },
            }
        ).encode()
        return ConfluenceHttpResponse(status_code=200, body=body)

    def get_bytes(self, *, path: str, query: Mapping[str, str]) -> bytes:
        self.calls.append(("attachment", path, dict(query)))
        return json.dumps(
            {
                "results": [
                    {"id": "2000", "type": "attachment", "title": SECRET_FILENAME}
                ],
                "_links": {},
            }
        ).encode()


def _install(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTransport.last = None
    monkeypatch.setattr(cli, "UrllibConfluenceHttpTransport", FakeTransport)


def _write_page(root: Path) -> None:
    target = root / "confluence" / "pages" / f"{PAGE_ID}.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(
        json.dumps({"id": PAGE_ID, "ancestors": [{"id": "900"}]}).encode()
    )


def _argv(root: Path) -> list[str]:
    return [
        "--page-id",
        PAGE_ID,
        "--raw-root",
        str(root),
        "--attachment-page-size",
        "2",
        "--max-attachment-pages",
        "10",
    ]


def _capture_argv(root: Path, target: Path) -> list[str]:
    return [
        *_argv(root),
        "--restriction-observations-sidecar-out",
        str(target),
    ]


def test_success_composes_production_adapters_and_prints_only_booleans(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_page(tmp_path)
    _install(monkeypatch)

    assert cli.main(_argv(tmp_path)) == 0

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        f"{name}=true" for name in cli._SUCCESS_CHECKS
    ]
    assert captured.err == ""
    transport = FakeTransport.last
    assert transport is not None
    assert [kind for kind, _path, _query in transport.calls] == [
        "restriction",
        "restriction",
        "attachment",
    ]
    for sensitive in (
        PAT,
        BASE_URL,
        PAGE_ID,
        "900",
        "2000",
        SECRET_FILENAME,
        SECRET_PRINCIPAL,
    ):
        assert sensitive not in captured.out
        assert sensitive not in captured.err


def test_default_mode_never_invokes_sidecar_validator_or_publisher(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_page(tmp_path)
    _install(monkeypatch)

    def explode(*args: object, **kwargs: object) -> object:
        raise AssertionError("default mode must not invoke sidecar components")

    monkeypatch.setattr(cli, "prepare_restriction_sidecar_target", explode)
    monkeypatch.setattr(cli, "serialize_restriction_observations", explode)
    monkeypatch.setattr(cli, "publish_restriction_sidecar", explode)

    assert cli.main(_argv(tmp_path)) == 0


def test_capture_mode_publishes_direct_result_and_appends_one_boolean(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    target = tmp_path / "external-captured-sidecar.json"
    _write_page(raw_root)
    _install(monkeypatch)

    assert cli.main(_capture_argv(raw_root, target)) == 0

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        *(f"{name}=true" for name in cli._SUCCESS_CHECKS),
        "restriction_sidecar_written=true",
    ]
    assert captured.err == ""
    payload = json.loads(target.read_bytes())
    assert set(payload) == {
        "format_version",
        "evidence_kind",
        "restriction_observations",
    }
    assert payload["format_version"] == "1.0"
    assert payload["evidence_kind"] == "captured_m6b_result"
    assert [
        observation["source_page_id"]
        for observation in payload["restriction_observations"]
    ] == ["900", PAGE_ID]
    assert SECRET_PRINCIPAL in target.read_text(encoding="utf-8")
    assert FakeTransport.last is not None
    assert len(FakeTransport.last.calls) == 3
    for sensitive in (
        str(target),
        target.name,
        PAT,
        BASE_URL,
        PAGE_ID,
        "900",
        SECRET_PRINCIPAL,
    ):
        assert sensitive not in captured.out
        assert sensitive not in captured.err


def test_cli_passes_the_exact_returned_observation_tuple_to_serializer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "sidecar.json"
    observations = (
        {
            "source_page_id": "1000",
            "http_status": 404,
            "classification": "unavailable",
            "users": [],
            "groups": [],
        },
    )
    result = PageObservationCollectionResult(
        restriction_observations=observations,
        attachment_observations=(),
        attachment_window_count=0,
    )
    run_calls = 0
    observed_identity = False

    def run(args: object) -> PageObservationCollectionResult:
        nonlocal run_calls
        run_calls += 1
        return result

    def serialize(value: object) -> bytes:
        nonlocal observed_identity
        observed_identity = value is observations
        return b'{"fixture":true}\n'

    monkeypatch.setattr(cli, "_run", run)
    monkeypatch.setattr(cli, "serialize_restriction_observations", serialize)

    assert cli.main(_capture_argv(tmp_path, target)) == 0
    assert run_calls == 1
    assert observed_identity is True
    assert target.read_bytes() == b'{"fixture":true}\n'


@pytest.mark.parametrize(
    "target_factory",
    [
        lambda tmp: Path("relative-sidecar.json"),
        lambda tmp: tmp / "missing" / "sidecar.json",
        lambda tmp: cli._resolve_repository_root(Path(cli.__file__))
        / "forbidden-sidecar.json",
    ],
    ids=("relative", "missing-parent", "repository-internal"),
)
def test_invalid_sidecar_target_precedes_credentials_transport_and_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target_factory: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = target_factory(tmp_path)  # type: ignore[operator]
    credential_reads = 0

    def read_credentials() -> tuple[str, str]:
        nonlocal credential_reads
        credential_reads += 1
        raise AssertionError("credentials must not be read")

    monkeypatch.setattr(cli, "_require_credentials", read_credentials)
    FakeTransport.last = None

    assert cli.main(_capture_argv(tmp_path, target)) == 11

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": "sidecar_target",
    }
    assert credential_reads == 0
    assert FakeTransport.last is None
    assert not target.exists()


def test_unresolved_repository_boundary_fails_before_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    credential_reads = 0

    def fail_root(module_path: Path) -> Path:
        raise RestrictionSidecarTargetError()

    def read_credentials() -> tuple[str, str]:
        nonlocal credential_reads
        credential_reads += 1
        raise AssertionError("credentials must not be read")

    monkeypatch.setattr(cli, "_resolve_repository_root", fail_root)
    monkeypatch.setattr(cli, "_require_credentials", read_credentials)

    assert cli.main(_capture_argv(tmp_path, tmp_path / "sidecar.json")) == 11
    assert credential_reads == 0


def test_repository_root_requires_both_locked_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert cli._resolve_repository_root(Path(cli.__file__)).is_dir()
    monkeypatch.setattr(
        cli,
        "_REPOSITORY_MARKERS",
        (Path("missing-c1-marker"),),
    )

    with pytest.raises(RestrictionSidecarTargetError):
        cli._resolve_repository_root(Path(cli.__file__))


@pytest.mark.parametrize(
    ("failure", "expected_exit", "expected_category"),
    [
        (
            RestrictionSidecarSerializationError(),
            12,
            "sidecar_serialization",
        ),
        (
            RestrictionSidecarPublicationError(),
            13,
            "sidecar_publication",
        ),
    ],
)
def test_post_collection_sidecar_failure_is_sanitized_and_preserves_raw_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failure: Exception,
    expected_exit: int,
    expected_category: str,
) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    target = tmp_path / "private-output-sidecar.json"
    _write_page(raw_root)
    _install(monkeypatch)

    if isinstance(failure, RestrictionSidecarSerializationError):
        def fail_serialize(observations: object) -> bytes:
            raise failure

        monkeypatch.setattr(
            cli, "serialize_restriction_observations", fail_serialize
        )
    else:
        def fail_publish(*args: object, **kwargs: object) -> None:
            raise failure

        monkeypatch.setattr(cli, "publish_restriction_sidecar", fail_publish)

    assert cli.main(_capture_argv(raw_root, target)) == expected_exit

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": expected_category,
    }
    assert not target.exists()
    assert (
        raw_root
        / "confluence"
        / "restrictions"
        / "view"
        / PAGE_ID
        / "900.body"
    ).is_file()
    assert (
        raw_root
        / "confluence"
        / "restrictions"
        / "view"
        / PAGE_ID
        / f"{PAGE_ID}.body"
    ).is_file()
    assert (
        raw_root
        / "confluence"
        / "attachments"
        / "metadata"
        / PAGE_ID
        / "start-0_limit-2.json"
    ).is_file()
    assert FakeTransport.last is not None
    assert len(FakeTransport.last.calls) == 3
    for sensitive in (
        str(target),
        target.name,
        PAT,
        BASE_URL,
        PAGE_ID,
        "900",
        SECRET_PRINCIPAL,
    ):
        assert sensitive not in captured.out
        assert sensitive not in captured.err


def test_missing_page_fails_before_network_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install(monkeypatch)

    assert cli.main(_argv(tmp_path)) == 4

    assert json.loads(capsys.readouterr().err)["category"] == "raw_page_input"
    assert FakeTransport.last is not None
    assert FakeTransport.last.calls == []


def test_pat_cannot_be_supplied_on_command_line_without_echo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install(monkeypatch)
    value = "REVIEW_SENTINEL_SECRET"

    assert cli.main([*_argv(tmp_path), "--pat", value]) == 2

    captured = capsys.readouterr()
    assert value not in captured.out
    assert value not in captured.err


@pytest.mark.parametrize("missing", [cli.BASE_URL_ENV, cli.PAT_ENV])
def test_missing_environment_credential_is_sanitized_configuration_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    missing: str,
) -> None:
    _write_page(tmp_path)
    _install(monkeypatch)
    monkeypatch.delenv(missing)

    assert cli.main(_argv(tmp_path)) == 2

    captured = capsys.readouterr()
    assert json.loads(captured.err)["category"] == "configuration"
    assert PAT not in captured.err
    assert BASE_URL not in captured.err
