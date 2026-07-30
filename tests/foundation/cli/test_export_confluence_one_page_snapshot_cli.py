from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases.normalize_confluence_page import (
    CATEGORY_INVALID_PAGE_ID,
    ConfluencePageNormalizationError,
)
from knowledgenexus.foundation.application.use_cases.project_one_page_export import (
    OnePageExportProjectionError,
)
from knowledgenexus.foundation.cli import export_confluence_one_page_snapshot as cli
from knowledgenexus.foundation.domain.models import (
    AclMaterializationError,
    ConfluenceAclCompositionAcceptanceError,
    ConfluenceAclRestrictionAncestryError,
)
from knowledgenexus.foundation.domain.models.acl_materialization import (
    AclMaterializationFailureCategory,
)
from knowledgenexus.foundation.domain.models.one_page_export import (
    OnePageExportCauseFamily,
    OnePageExportConfigurationError,
    OnePageExportStage,
)
from knowledgenexus.foundation.domain.models.one_page_export_snapshot import (
    OnePageExportAcceptanceResult,
    OnePageFullSnapshotExportResult,
)
from knowledgenexus.foundation.infrastructure.exporters.one_page_full_snapshot_exporter import (
    OnePageFullSnapshotExportError,
)
from knowledgenexus.foundation.infrastructure.sidecars import (
    CAPTURED_M6B_EVIDENCE_KIND,
    SYNTHETIC_FIXTURE_EVIDENCE_KIND,
    RestrictionSidecarLoadError,
)
from knowledgenexus.foundation.ports.raw_page_observation_store_port import (
    RawPageReadError,
)
from tests.fixtures.foundation.one_page_export_snapshot_fixtures import (
    build_one_page_export_projection,
)
from tests.fixtures.foundation.record_factories import (
    build_sample_acl_record,
    build_sample_chunk_record,
    build_sample_document_record,
    build_sample_relation_record,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CHUNK_PROFILE_PATH = (
    REPOSITORY_ROOT / "contracts" / "foundation" / "embedding_profile.yaml"
)
JIRA_PROFILE_PATH = (
    REPOSITORY_ROOT / "contracts" / "foundation" / "jira_relation_profile.yaml"
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
        "--generated-at",
        "2026-07-24T00:00:03Z",
        "--export-root",
        "C:/SENSITIVE/EXPORT",
    ]


def _outcome(evidence_kind: str = CAPTURED_M6B_EVIDENCE_KIND) -> cli._RunOutcome:
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
        projection_deterministic=True,
        raw_page_unchanged=True,
        sidecar_unchanged=True,
        manifest_schema_valid=True,
        manifest_counts_match=True,
        records_match_projection=True,
        deferred_streams_empty=True,
        final_file_set_valid=True,
        quality_report_unchanged=True,
        latest_pointer_valid=True,
    )


# --- argument parsing ---------------------------------------------------------


def test_missing_required_argument_is_configuration_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = _argv()[:-2]  # drop the --export-root flag and its value entirely
    assert cli.main(argv) == cli.EXIT_CONFIGURATION
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": "configuration",
    }


def test_prog_name_is_locked() -> None:
    source = inspect.getsource(cli._parse_args)
    assert 'prog="export-confluence-one-page-snapshot"' in source


# --- success -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("evidence_kind", "real_captured"),
    [
        (CAPTURED_M6B_EVIDENCE_KIND, True),
        (SYNTHETIC_FIXTURE_EVIDENCE_KIND, False),
    ],
)
def test_success_is_one_sanitized_json_line(
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
        "network_used": False,
        "credentials_used": False,
        "restriction_ancestry_bound": True,
        "acl_record_schema_valid": True,
        "chunks_schema_valid": True,
        "canonical_unchanged": True,
        "relations_unchanged": True,
        "chunk_non_acl_fields_unchanged": True,
        "chunk_acl_tags_match_acl_record": True,
        "deterministic_repeat": True,
        "projection_deterministic": True,
        "raw_page_unchanged": True,
        "sidecar_unchanged": True,
        "output_files_created": True,
        "manifest_schema_valid": True,
        "manifest_counts_match": True,
        "records_match_projection": True,
        "deferred_streams_empty": True,
        "final_file_set_valid": True,
        "quality_report_complete": True,
        "quality_report_unchanged": True,
        "latest_pointer_valid": True,
    }
    for forbidden in ("SENSITIVE", "C:/SENSITIVE"):
        assert forbidden not in captured.out


def test_success_never_leaks_sensitive_argv_values(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_run", lambda args: _outcome())
    assert cli.main(_argv()) == 0
    captured = capsys.readouterr()
    assert "SENSITIVE" not in captured.out
    assert "SENSITIVE" not in captured.err


# --- exit-code taxonomy: 1-13 preserved exactly (R3: never 5 or 8) -----------


@pytest.mark.parametrize(
    ("failure", "exit_code", "category"),
    [
        (
            ConfluencePageNormalizationError(CATEGORY_INVALID_PAGE_ID),
            cli.EXIT_NORMALIZATION,
            "invalid_page_id",
        ),
        (
            RestrictionSidecarLoadError(),
            cli.EXIT_RESTRICTION_SIDECAR,
            "restriction_sidecar",
        ),
        (
            ConfluenceAclRestrictionAncestryError(),
            cli.EXIT_RESTRICTION_ANCESTRY,
            "restriction_ancestry",
        ),
        (
            ConfluenceAclCompositionAcceptanceError(),
            cli.EXIT_ACCEPTANCE,
            "acceptance",
        ),
        (cli._AcceptanceError(), cli.EXIT_ACCEPTANCE, "acceptance"),
        (
            cli._PreExportSourceMutationError(),
            cli.EXIT_ACCEPTANCE,
            "acceptance",
        ),
        (RuntimeError("SENSITIVE"), cli.EXIT_UNEXPECTED, "unexpected"),
        (KeyboardInterrupt("SENSITIVE"), cli.EXIT_UNEXPECTED, "unexpected"),
    ],
)
def test_existing_c2_style_failures_are_sanitized(
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
    assert json.loads(captured.err) == {"status": "failed", "category": category}
    assert "SENSITIVE" not in captured.err


def test_acl_materialization_error_maps_exact_category(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(args: object) -> object:
        raise AclMaterializationError(
            AclMaterializationFailureCategory.INVALID_EXTRACTED_AT
        )

    monkeypatch.setattr(cli, "_run", fail)

    assert cli.main(_argv()) == cli.EXIT_ACL_MATERIALIZATION
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": "invalid_extracted_at",
    }


# --- exit-code taxonomy: 14-19 (new) -----------------------------------------


def test_profile_bundle_failure_maps_to_export_configuration_14(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(args: object) -> object:
        raise OnePageExportConfigurationError(
            stage=OnePageExportStage.EMBEDDING_PROFILE_READ,
            cause_family=OnePageExportCauseFamily.IO_ERROR,
        )

    monkeypatch.setattr(cli, "_run", fail)

    assert cli.main(_argv()) == cli.EXIT_EXPORT_CONFIGURATION
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": "export_configuration",
        "stage": "embedding_profile_read",
        "cause_family": "io_error",
    }


def test_projection_failure_maps_to_export_projection_15(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(args: object) -> object:
        raise OnePageExportProjectionError()

    monkeypatch.setattr(cli, "_run", fail)

    assert cli.main(_argv()) == cli.EXIT_EXPORT_PROJECTION
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": "export_projection",
    }


@pytest.mark.parametrize(
    ("category", "exit_code"),
    [
        ("export_projection", cli.EXIT_EXPORT_PROJECTION),
        ("export_staging", cli.EXIT_EXPORT_STAGING),
        ("export_completion", cli.EXIT_EXPORT_COMPLETION),
        ("export_publication", cli.EXIT_EXPORT_PUBLICATION),
        ("export_acceptance", cli.EXIT_EXPORT_ACCEPTANCE),
    ],
)
def test_exporter_error_category_maps_to_correct_exit_code(
    category: str,
    exit_code: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(args: object) -> object:
        raise OnePageFullSnapshotExportError(category)

    monkeypatch.setattr(cli, "_run", fail)

    assert cli.main(_argv()) == exit_code
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {"status": "failed", "category": category}
    assert "SENSITIVE" not in captured.err


def test_generic_failure_helper_cannot_accept_configuration_metadata() -> None:
    signature = inspect.signature(cli._fail)
    assert "stage" not in signature.parameters
    assert "cause_family" not in signature.parameters


@pytest.mark.parametrize("marker", ["SENSITIVE", "https://internal.invalid", "a" * 64])
def test_configuration_failure_never_leaks_runtime_markers(
    marker: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(args: object) -> object:
        error = OnePageExportConfigurationError(
            stage=OnePageExportStage.PROFILE_BUNDLE_CONSTRUCTION,
            cause_family=OnePageExportCauseFamily.VALUE_ERROR,
        )
        error.__context__ = ValueError(marker)
        raise error

    monkeypatch.setattr(cli, "_run", fail)

    assert cli.main(_argv()) == cli.EXIT_EXPORT_CONFIGURATION
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert payload == {
        "status": "failed",
        "category": "export_configuration",
        "stage": "profile_bundle_construction",
        "cause_family": "value_error",
    }
    assert marker not in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_post_publication_source_mutation_maps_to_export_acceptance_19(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(args: object) -> object:
        raise cli._PostPublicationSourceMutationError()

    monkeypatch.setattr(cli, "_run", fail)

    assert cli.main(_argv()) == cli.EXIT_EXPORT_ACCEPTANCE
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": "export_acceptance",
    }


def test_exit_codes_5_and_8_are_reserved_but_unused_constants() -> None:
    used_exit_codes = {
        value
        for name, value in vars(cli).items()
        if name.startswith("EXIT_") and isinstance(value, int)
    }
    assert 5 not in used_exit_codes
    assert 8 not in used_exit_codes


def test_exit_code_taxonomy_has_no_duplicate_values() -> None:
    exit_codes = [
        value
        for name, value in vars(cli).items()
        if name.startswith("EXIT_") and isinstance(value, int)
    ]
    assert len(exit_codes) == len(set(exit_codes))


# --- P1: leaky M3 loggers must never reach stdout/stderr ---------------------


def test_leaky_m3_loggers_are_silenced_after_main_runs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_run", lambda args: _outcome())
    cli.main(_argv())
    capsys.readouterr()  # discard the CLI's own sanitized stdout

    for name in cli._LEAKY_M3_LOGGER_NAMES:
        logging.getLogger(name).warning(
            "Failed to remove owned file: %s",
            "C:\\SENSITIVE\\export.tmp",
            exc_info=True,
        )

    leaked = capsys.readouterr()
    assert leaked.out == ""
    assert leaked.err == ""


# --- P2a: real _run() traversal for raw-page reread failures -----------------


class _FakeRawStore:
    def __init__(self, raw_bytes: bytes, fail_on_call: int | None) -> None:
        self._raw_bytes = raw_bytes
        self._fail_on_call = fail_on_call
        self.call_count = 0

    def read_page(self, *, page_id: str) -> bytes:
        self.call_count += 1
        if self._fail_on_call is not None and self.call_count == self._fail_on_call:
            raise RawPageReadError("fixture forced read failure")
        return self._raw_bytes


@dataclass(frozen=True)
class _FakeJiraRelationResult:
    enriched_canonical_document: dict
    relations: tuple
    enriched_chunks: tuple


@dataclass(frozen=True)
class _FakeAclMaterializationResult:
    enriched_canonical_document: dict
    relations: tuple
    enriched_chunks: tuple
    acl_record: dict


@dataclass(frozen=True)
class _FakeCompositionResult:
    jira_relation_result: _FakeJiraRelationResult
    acl_materialization_result: _FakeAclMaterializationResult


class _FakeComposeConfluenceAcl:
    def __init__(self, **kwargs: object) -> None:
        pass

    def execute(self, **kwargs: object) -> _FakeCompositionResult:
        document = build_sample_document_record()
        chunk = build_sample_chunk_record()
        relation = build_sample_relation_record()
        acl_record = build_sample_acl_record()
        return _FakeCompositionResult(
            jira_relation_result=_FakeJiraRelationResult(
                enriched_canonical_document=document,
                relations=(relation,),
                enriched_chunks=(chunk,),
            ),
            acl_materialization_result=_FakeAclMaterializationResult(
                enriched_canonical_document=document,
                relations=(relation,),
                enriched_chunks=(chunk,),
                acl_record=acl_record,
            ),
        )


class _FakeProjectOnePageExport:
    def __init__(self, **kwargs: object) -> None:
        pass

    def execute(self, **kwargs: object) -> object:
        return build_one_page_export_projection()


class _FakeExporter:
    @staticmethod
    def export(**kwargs: object) -> OnePageFullSnapshotExportResult:
        return OnePageFullSnapshotExportResult(
            dataset_version="v20260101-000000-000000Z",
            final_path=Path("fake-final-path"),
            manifest={"dataset_version": "v20260101-000000-000000Z"},
            acceptance=OnePageExportAcceptanceResult(
                final_file_set_valid=True,
                manifest_schema_valid=True,
                manifest_version_matches_directory=True,
                manifest_metadata_matches_projection=True,
                manifest_counts_match=True,
                records_match_projection=True,
                deferred_streams_empty=True,
                quality_report_unchanged_after_publication=True,
                latest_pointer_valid=True,
            ),
        )


def _wire_fakes_and_real_argv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    raw_fail_on_call: int | None = None,
) -> list[str]:
    # Exercises the REAL _run() control flow (raw-page reread, sidecar
    # reread, source-mutation checks) with only the heavy collaborators
    # (tokenizer, ComposeConfluenceAcl, ProjectOnePageExport, the exporter)
    # faked out, so this is not just re-testing main()'s dispatch table.
    raw_bytes = b'{"fixture": "raw-page"}'
    sidecar_path = tmp_path / "sidecar.json"
    sidecar_path.write_text(
        json.dumps(
            {
                "format_version": "1.0",
                "evidence_kind": SYNTHETIC_FIXTURE_EVIDENCE_KIND,
                "restriction_observations": [],
            }
        ),
        encoding="utf-8",
    )

    fake_store = _FakeRawStore(raw_bytes, raw_fail_on_call)
    monkeypatch.setattr(
        cli, "ConfluencePageObservationStore", lambda *, raw_root: fake_store
    )
    monkeypatch.setattr(cli, "BgeM3LocalTokenizer", lambda **kwargs: object())
    monkeypatch.setattr(cli, "ComposeConfluenceAcl", _FakeComposeConfluenceAcl)
    monkeypatch.setattr(cli, "ProjectOnePageExport", _FakeProjectOnePageExport)
    monkeypatch.setattr(cli, "OnePageFullSnapshotExporter", _FakeExporter)

    return [
        "--page-id",
        "1000",
        "--raw-root",
        str(tmp_path / "raw"),
        "--profile-path",
        str(CHUNK_PROFILE_PATH),
        "--tokenizer-assets-dir",
        str(tmp_path / "assets"),
        "--jira-profile-path",
        str(JIRA_PROFILE_PATH),
        "--crawled-at",
        "2026-07-24T00:00:00Z",
        "--relation-created-at",
        "2026-07-24T00:00:01Z",
        "--restriction-sidecar-path",
        str(sidecar_path),
        "--crawler-identity",
        "fixture-crawler",
        "--acl-extracted-at",
        "2026-07-24T00:00:02Z",
        "--generated-at",
        "2026-07-24T00:00:03Z",
        "--export-root",
        str(tmp_path / "export"),
    ]


def test_real_run_succeeds_end_to_end_with_faked_collaborators(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = _wire_fakes_and_real_argv(monkeypatch, tmp_path)

    assert cli.main(argv) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["status"] == "success"


def test_real_pre_export_raw_reread_failure_maps_to_acceptance_13(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The 2nd raw_store.read_page call is the pre-export reread.
    argv = _wire_fakes_and_real_argv(monkeypatch, tmp_path, raw_fail_on_call=2)

    assert cli.main(argv) == cli.EXIT_ACCEPTANCE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"status": "failed", "category": "acceptance"}


def test_real_post_publication_raw_reread_failure_maps_to_export_acceptance_19(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The 3rd raw_store.read_page call is the post-publication reread.
    argv = _wire_fakes_and_real_argv(monkeypatch, tmp_path, raw_fail_on_call=3)

    assert cli.main(argv) == cli.EXIT_EXPORT_ACCEPTANCE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": "export_acceptance",
    }
