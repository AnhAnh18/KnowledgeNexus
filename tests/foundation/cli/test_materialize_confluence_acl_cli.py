from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli import materialize_confluence_acl as cli
from knowledgenexus.foundation.application.use_cases.normalize_confluence_page import (
    ConfluencePageNormalizationError,
)
from knowledgenexus.foundation.domain.models.acl_materialization import (
    AclMaterializationFailureCategory,
)
from knowledgenexus.foundation.infrastructure.sidecars import (
    CAPTURED_M6B_EVIDENCE_KIND,
    SYNTHETIC_FIXTURE_EVIDENCE_KIND,
    LoadedRestrictionSidecar,
    RestrictionSidecarLoadError,
)
from knowledgenexus.foundation.ports.raw_page_observation_store_port import (
    RawPageReadError,
)


def _argv() -> list[str]:
    return [
        "--page-id",
        "1000",
        "--raw-root",
        "C:/SENSITIVE/RAW",
        "--profile-path",
        "C:/SENSITIVE/CHUNK.yaml",
        "--tokenizer-assets-dir",
        "C:/SENSITIVE/ASSETS",
        "--jira-profile-path",
        "C:/SENSITIVE/JIRA.yaml",
        "--crawled-at",
        "2026-07-24T00:00:00Z",
        "--relation-created-at",
        "2026-07-24T00:00:01Z",
        "--restriction-sidecar-path",
        "C:/SENSITIVE/sidecar.json",
        "--crawler-identity",
        "SENSITIVE-CRAWLER",
        "--acl-extracted-at",
        "2026-07-24T00:00:02Z",
    ]


def _outcome(
    evidence_kind: str = CAPTURED_M6B_EVIDENCE_KIND,
) -> cli._RunOutcome:
    return cli._RunOutcome(
        evidence_kind=evidence_kind,
        restriction_ancestry_bound=True,
        acl_record_schema_valid=True,
        chunks_schema_valid=True,
        canonical_unchanged=True,
        relations_unchanged=True,
        chunk_non_acl_fields_unchanged=True,
        chunk_acl_tags_match_acl_record=True,
        deterministic_repeat=True,
        raw_page_unchanged=True,
        sidecar_unchanged=True,
    )


@pytest.mark.parametrize(
    ("evidence_kind", "real_captured"),
    [
        (CAPTURED_M6B_EVIDENCE_KIND, True),
        (SYNTHETIC_FIXTURE_EVIDENCE_KIND, False),
    ],
)
def test_success_is_one_aggregate_only_json_line(
    evidence_kind: str,
    real_captured: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_run", lambda args: _outcome(evidence_kind))

    assert cli.main(_argv()) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert json.loads(captured.out) == {
        "status": "success",
        "restriction_evidence_kind": evidence_kind,
        "real_captured_evidence": real_captured,
        "restriction_ancestry_bound": True,
        "acl_record_schema_valid": True,
        "chunks_schema_valid": True,
        "canonical_unchanged": True,
        "relations_unchanged": True,
        "chunk_non_acl_fields_unchanged": True,
        "chunk_acl_tags_match_acl_record": True,
        "deterministic_repeat": True,
        "raw_page_unchanged": True,
        "sidecar_unchanged": True,
        "network_used": False,
        "output_files_created": False,
    }
    assert "SENSITIVE" not in captured.out


@pytest.mark.parametrize(
    ("failure", "exit_code", "category"),
    [
        (
            RestrictionSidecarLoadError(),
            cli.EXIT_RESTRICTION_SIDECAR,
            "restriction_sidecar",
        ),
        (
            cli._RestrictionAncestryError(),
            cli.EXIT_RESTRICTION_ANCESTRY,
            "restriction_ancestry",
        ),
        (
            cli._AclMaterializationStageError("invalid_crawler_identity"),
            cli.EXIT_ACL_MATERIALIZATION,
            "invalid_crawler_identity",
        ),
        (cli._AcceptanceError(), cli.EXIT_ACCEPTANCE, "acceptance"),
        (RuntimeError("SENSITIVE"), cli.EXIT_UNEXPECTED, "unexpected"),
        (KeyboardInterrupt("SENSITIVE"), cli.EXIT_UNEXPECTED, "unexpected"),
    ],
)
def test_stage_failures_are_sanitized(
    failure: BaseException,
    exit_code: int,
    category: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(args: object) -> object:
        raise failure

    monkeypatch.setattr(cli, "_run", fail)

    assert cli.main(_argv()) == exit_code
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": category,
    }
    assert "SENSITIVE" not in captured.err


@pytest.mark.parametrize(
    ("failure", "exit_code", "category"),
    [
        (
            cli.ConfluenceAclRestrictionAncestryError(),
            cli.EXIT_RESTRICTION_ANCESTRY,
            "restriction_ancestry",
        ),
        (cli.ConfluenceAclCompositionAcceptanceError(), cli.EXIT_ACCEPTANCE, "acceptance"),
    ],
)
def test_reusable_composition_domain_failures_are_sanitized(
    failure: BaseException,
    exit_code: int,
    category: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(args: object) -> object:
        raise failure

    monkeypatch.setattr(cli, "_run", fail)

    assert cli.main(_argv()) == exit_code
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": category,
    }


def test_acl_materialization_error_from_composition_maps_exact_category(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(args: object) -> object:
        raise cli.AclMaterializationError(
            AclMaterializationFailureCategory.INVALID_EXTRACTED_AT
        )

    monkeypatch.setattr(cli, "_run", fail)

    assert cli.main(_argv()) == cli.EXIT_ACL_MATERIALIZATION
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": "invalid_extracted_at",
    }


@pytest.mark.parametrize("number", ("1e309", "-1e309", "1e999999"))
def test_exponent_overflow_sidecar_fails_at_initial_loader_boundary(
    tmp_path: Path,
    number: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sidecar_path = tmp_path / "sensitive-sidecar.json"
    sidecar_path.write_bytes(
        (
            '{"format_version":"1.0",'
            '"evidence_kind":"captured_m6b_result",'
            '"restriction_observations":[{'
            '"source_page_id":"1000",'
            f'"http_status":{number},'
            '"classification":"unavailable",'
            '"users":[],"groups":[]}]}'
        ).encode("ascii")
    )
    monkeypatch.setattr(
        cli,
        "_read_raw_page",
        lambda **_kwargs: _raw_page(),
    )
    args = _argv()
    args[args.index("--raw-root") + 1] = str(tmp_path / "raw")
    args[args.index("--restriction-sidecar-path") + 1] = str(sidecar_path)

    assert cli.main(args) == cli.EXIT_RESTRICTION_SIDECAR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": "restriction_sidecar",
    }
    assert number not in captured.err
    assert sidecar_path.name not in captured.err


def test_dot_dot_sidecar_path_fails_at_initial_loader_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    traversed_parent = tmp_path / "safe" / "a"
    traversed_parent.mkdir(parents=True)
    sidecar_path = traversed_parent / ".." / "target" / "sidecar.json"
    monkeypatch.setattr(
        cli,
        "_read_raw_page",
        lambda **_kwargs: _raw_page(),
    )
    args = _argv()
    args[args.index("--raw-root") + 1] = str(tmp_path / "raw")
    args[args.index("--restriction-sidecar-path") + 1] = str(sidecar_path)

    assert cli.main(args) == cli.EXIT_RESTRICTION_SIDECAR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": "restriction_sidecar",
    }
    assert str(sidecar_path) not in captured.err


def test_argparse_failure_never_echoes_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--page-id", "SENSITIVE-PAGE"]) == cli.EXIT_CONFIGURATION
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": "configuration",
    }
    assert "SENSITIVE" not in captured.err


def test_invalid_page_id_preserves_existing_normalization_mapping(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _argv()
    args[1] = "SENSITIVE-PAGE"

    assert cli.main(args) == cli.EXIT_NORMALIZATION

    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": "invalid_page_id",
    }
    assert "SENSITIVE" not in captured.err


def _raw_page(
    *,
    page_id: str = "1000",
    ancestors: list[str] | None = None,
) -> bytes:
    return json.dumps(
        {
            "id": page_id,
            "ancestors": [
                {"id": ancestor} for ancestor in (ancestors or ["800", "900"])
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _loaded(ids: list[str]) -> LoadedRestrictionSidecar:
    return LoadedRestrictionSidecar(
        evidence_kind=SYNTHETIC_FIXTURE_EVIDENCE_KIND,
        restriction_observations=tuple(
            {
                "source_page_id": page_id,
                "http_status": 200,
                "classification": "unrestricted",
                "users": [],
                "groups": [],
            }
            for page_id in ids
        ),
    )


class _SequenceRawStore:
    values: list[bytes | BaseException] = []

    def __init__(self, *, raw_root: Path) -> None:
        self._values = list(type(self).values)

    def read_page(self, *, page_id: str) -> bytes:
        value = self._values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class _StubComposer:
    """Stands in for ``ComposeConfluenceAcl`` so ``_run()``'s own raw/sidecar
    before-after reread logic can be exercised without a real composition."""

    def __init__(self, **_kwargs: object) -> None:
        pass

    def execute(self, **_kwargs: object) -> object:
        return object()


def _run_args() -> Namespace:
    values = _argv()
    return cli._parse_args(values)


def _stub_run_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    raw_values: list[bytes | BaseException],
    sidecar_values: list[object],
) -> None:
    _SequenceRawStore.values = raw_values
    monkeypatch.setattr(cli, "ConfluencePageObservationStore", _SequenceRawStore)
    monkeypatch.setattr(cli, "load_chunking_profile", lambda path: object())
    monkeypatch.setattr(cli, "load_jira_relation_profile", lambda path: object())
    monkeypatch.setattr(
        cli,
        "BgeM3LocalTokenizer",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(cli, "ComposeConfluenceAcl", _StubComposer)
    calls = iter(sidecar_values)

    def load(path: Path) -> object:
        value = next(calls)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(cli, "load_restriction_sidecar", load)


def test_raw_page_byte_change_after_composition_is_acceptance_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = _loaded(["1000"])
    _stub_run_dependencies(
        monkeypatch,
        raw_values=[b"before", b"after"],
        sidecar_values=[(loaded, b"sidecar"), (loaded, b"sidecar")],
    )

    with pytest.raises(cli._AcceptanceError):
        cli._run(_run_args())


def test_final_raw_reread_failure_retains_normalization_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = _loaded(["1000"])
    _stub_run_dependencies(
        monkeypatch,
        raw_values=[b"before", RawPageReadError("SENSITIVE")],
        sidecar_values=[(loaded, b"sidecar")],
    )

    with pytest.raises(ConfluencePageNormalizationError) as captured:
        cli._run(_run_args())

    assert captured.value.category == cli.CATEGORY_RAW_PAGE_INPUT


@pytest.mark.parametrize(
    "final_sidecar",
    [
        (_loaded(["1000"]), b"changed"),
        RestrictionSidecarLoadError(),
    ],
)
def test_final_sidecar_change_or_reread_failure_is_acceptance_failure(
    final_sidecar: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = _loaded(["1000"])
    _stub_run_dependencies(
        monkeypatch,
        raw_values=[b"same", b"same"],
        sidecar_values=[(loaded, b"sidecar"), final_sidecar],
    )

    with pytest.raises(cli._AcceptanceError):
        cli._run(_run_args())
