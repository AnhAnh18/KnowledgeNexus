from __future__ import annotations

import json
from argparse import Namespace
from copy import deepcopy
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli import materialize_confluence_acl as cli
from knowledgenexus.foundation.application.use_cases.normalize_confluence_page import (
    ConfluencePageNormalizationError,
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


def test_fixed_raw_reader_returns_only_bound_snapshot() -> None:
    reader = cli._FixedRawPageReader(
        expected_page_id="1000",
        raw_bytes=b"SENSITIVE-RAW",
    )

    assert reader.read_page(page_id="1000") == b"SENSITIVE-RAW"
    with pytest.raises(RawPageReadError):
        reader.read_page(page_id="1001")
    assert "1000" not in repr(reader)
    assert "SENSITIVE" not in repr(reader)


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


def test_exact_ancestry_binding_preserves_validated_order() -> None:
    loaded = _loaded(["800", "900", "1000"])

    validated = cli._bind_restriction_ancestry(
        loaded_sidecar=loaded,
        canonical_page_id="1000",
        raw_bytes=_raw_page(),
        selected_page_id="1000",
    )

    assert tuple(item["source_page_id"] for item in validated) == (
        "800",
        "900",
        "1000",
    )


@pytest.mark.parametrize(
    ("ids", "raw_bytes", "canonical_page_id", "selected_page_id"),
    [
        (["900", "1000"], _raw_page(), "1000", "1000"),
        (["700", "800", "900", "1000"], _raw_page(), "1000", "1000"),
        (["900", "800", "1000"], _raw_page(), "1000", "1000"),
        (["800", "1000", "900"], _raw_page(), "1000", "1000"),
        (["800", "900", "1001"], _raw_page(), "1000", "1000"),
        (["800", "900", "1000", "1000"], _raw_page(), "1000", "1000"),
        (
            ["800", "900", "1000"],
            _raw_page(page_id="1001"),
            "1000",
            "1000",
        ),
        (
            ["800", "900", "1000"],
            _raw_page(ancestors=["800", "800"]),
            "1000",
            "1000",
        ),
        (
            ["800", "900", "1000"],
            _raw_page(ancestors=["800", "1000"]),
            "1000",
            "1000",
        ),
        (
            ["800", "900", "1000"],
            b'{"id":"1000","ancestors":{}}',
            "1000",
            "1000",
        ),
        (
            ["800", "900", "1000"],
            b"not-json",
            "1000",
            "1000",
        ),
    ],
)
def test_invalid_or_mismatched_ancestry_fails_in_stage_11(
    ids: list[str],
    raw_bytes: bytes,
    canonical_page_id: str,
    selected_page_id: str,
) -> None:
    with pytest.raises(cli._RestrictionAncestryError):
        cli._bind_restriction_ancestry(
            loaded_sidecar=_loaded(ids),
            canonical_page_id=canonical_page_id,
            raw_bytes=raw_bytes,
            selected_page_id=selected_page_id,
        )


def test_ancestry_binding_does_not_mutate_loaded_observations() -> None:
    loaded = _loaded(["800", "900", "1000"])
    before = deepcopy(loaded)

    cli._bind_restriction_ancestry(
        loaded_sidecar=loaded,
        canonical_page_id="1000",
        raw_bytes=_raw_page(),
        selected_page_id="1000",
    )

    assert loaded == before


class _SequenceRawStore:
    values: list[bytes | BaseException] = []

    def __init__(self, *, raw_root: Path) -> None:
        self._values = list(type(self).values)

    def read_page(self, *, page_id: str) -> bytes:
        value = self._values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


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
    monkeypatch.setattr(cli, "_compose_once", lambda **kwargs: object())
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
