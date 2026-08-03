from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_restriction_artifact import (
    ConfluenceRawRestrictionPublicationOutcome,
)
from knowledgenexus.foundation.domain.models.confluence_restriction_evidence import (
    M7_RESTRICTION_REQUEST_PROFILE_VERSION,
    ConfluenceRestrictionEvidenceEnvelope,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluenceRawRestrictionEvidenceStore,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    confluence_raw_restriction_store as store_module,
)
from knowledgenexus.foundation.ports.confluence_raw_restriction_store_port import (
    ConfluenceRawRestrictionStoreError,
    ConfluenceRawRestrictionStoreFailureCategory as FailureCategory,
)


RUN_ID = CrawlRunId("12345678-1234-4234-8234-123456789abc")
OTHER_RUN_ID = CrawlRunId("12345678-1234-4234-9234-123456789abc")


def _envelope(*, status: int = 200, target: str = "1001", body: bytes = b"body"):
    return ConfluenceRestrictionEvidenceEnvelope.capture(
        request_profile_version=M7_RESTRICTION_REQUEST_PROFILE_VERSION,
        selected_page_id="1000",
        target_page_id=target,
        http_status=status,
        body_bytes=body,
    )


def _store(tmp_path: Path) -> ConfluenceRawRestrictionEvidenceStore:
    return ConfluenceRawRestrictionEvidenceStore(raw_root=tmp_path)


def _error_category(callable_object, *args, **kwargs) -> str:
    with pytest.raises(ConfluenceRawRestrictionStoreError) as exc_info:
        callable_object(*args, **kwargs)
    return str(exc_info.value)


def test_publish_derives_generation_scoped_path_and_reads_back(tmp_path: Path) -> None:
    store = _store(tmp_path)
    envelope = _envelope()

    result = store.publish_restriction(run_id=RUN_ID, envelope=envelope)

    expected = (
        tmp_path
        / "confluence"
        / "generations"
        / str(RUN_ID)
        / "restrictions"
        / "1000"
        / "1001.json"
    )
    assert result.path == expected
    assert result.run_id == RUN_ID
    assert result.outcome is ConfluenceRawRestrictionPublicationOutcome.PUBLISHED
    assert expected.read_bytes() == envelope.to_bytes()
    assert store.read_restriction(
        run_id=RUN_ID, selected_page_id="1000", target_page_id="1001"
    ) == envelope


def test_identical_same_run_replay_reuses_without_replacement(tmp_path: Path) -> None:
    store = _store(tmp_path)
    envelope = _envelope()
    first = store.publish_restriction(run_id=RUN_ID, envelope=envelope)
    target = first.path
    before = target.stat()

    second = store.publish_restriction(run_id=RUN_ID, envelope=envelope)

    assert second.outcome is ConfluenceRawRestrictionPublicationOutcome.REUSED
    assert second.path == target
    assert target.read_bytes() == envelope.to_bytes()
    after = target.stat()
    assert (after.st_ino, after.st_size) == (before.st_ino, before.st_size)


@pytest.mark.parametrize(
    "envelope",
    [_envelope(body=b"different"), _envelope(status=404), _envelope(target="1002")],
)
def test_same_path_different_evidence_fails_closed(
    tmp_path: Path, envelope: ConfluenceRestrictionEvidenceEnvelope
) -> None:
    store = _store(tmp_path)
    store.publish_restriction(run_id=RUN_ID, envelope=_envelope())

    if envelope.target_page_id == "1002":
        # A different target has a different derived path and is a new key.
        result = store.publish_restriction(run_id=RUN_ID, envelope=envelope)
        assert result.outcome is ConfluenceRawRestrictionPublicationOutcome.PUBLISHED
        return

    assert (
        _error_category(store.publish_restriction, run_id=RUN_ID, envelope=envelope)
        == FailureCategory.RAW_REPLAY_CONFLICT
    )


def test_distinct_generation_uses_distinct_path(tmp_path: Path) -> None:
    store = _store(tmp_path)
    envelope = _envelope()

    first = store.publish_restriction(run_id=RUN_ID, envelope=envelope)
    second = store.publish_restriction(run_id=OTHER_RUN_ID, envelope=envelope)

    assert first.path != second.path
    assert first.path.exists() and second.path.exists()


def test_existing_path_envelope_identity_mismatch_is_not_overwritten(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    target = store.resolve_restriction_path(
        run_id=RUN_ID, selected_page_id="1000", target_page_id="1001"
    )
    target.parent.mkdir(parents=True)
    target.write_bytes(_envelope(target="1002").to_bytes())
    before = target.read_bytes()

    category = _error_category(
        store.publish_restriction, run_id=RUN_ID, envelope=_envelope()
    )

    assert category == FailureCategory.RAW_IDENTITY_MISMATCH
    assert target.read_bytes() == before


def test_malformed_or_noncanonical_existing_path_is_not_overwritten(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    target = store.resolve_restriction_path(
        run_id=RUN_ID, selected_page_id="1000", target_page_id="1001"
    )
    target.parent.mkdir(parents=True)
    malformed = b"{\"not\":\"m7\"}"
    target.write_bytes(malformed)

    assert (
        _error_category(
            store.publish_restriction, run_id=RUN_ID, envelope=_envelope()
        )
        == FailureCategory.RAW_ARTIFACT_INVALID
    )
    assert target.read_bytes() == malformed


def test_decoded_equivalent_but_noncanonical_existing_bytes_conflict_as_invalid(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    target = store.resolve_restriction_path(
        run_id=RUN_ID, selected_page_id="1000", target_page_id="1001"
    )
    target.parent.mkdir(parents=True)
    target.write_bytes(_envelope().to_bytes() + b"\n")

    assert (
        _error_category(
            store.publish_restriction, run_id=RUN_ID, envelope=_envelope()
        )
        == FailureCategory.RAW_ARTIFACT_INVALID
    )


def test_temporary_only_residue_is_not_treated_as_published(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    target = store.resolve_restriction_path(
        run_id=RUN_ID, selected_page_id="1000", target_page_id="1001"
    )
    target.parent.mkdir(parents=True)
    residue = target.parent / f".{target.name}.orphan.tmp"
    residue.write_bytes(b"partial")

    result = store.publish_restriction(run_id=RUN_ID, envelope=_envelope())

    assert result.outcome is ConfluenceRawRestrictionPublicationOutcome.PUBLISHED
    assert residue.read_bytes() == b"partial"


def test_target_directory_fails_without_delete(tmp_path: Path) -> None:
    store = _store(tmp_path)
    target = store.resolve_restriction_path(
        run_id=RUN_ID, selected_page_id="1000", target_page_id="1001"
    )
    target.parent.mkdir(parents=True)
    target.mkdir()

    assert (
        _error_category(
            store.publish_restriction, run_id=RUN_ID, envelope=_envelope()
        )
        == FailureCategory.RAW_ARTIFACT_INVALID
    )
    assert target.is_dir()


def test_target_symlink_fails_without_follow_or_delete(tmp_path: Path) -> None:
    store = _store(tmp_path)
    target = store.resolve_restriction_path(
        run_id=RUN_ID, selected_page_id="1000", target_page_id="1001"
    )
    target.parent.mkdir(parents=True)
    source = tmp_path / "outside.json"
    source.write_bytes(b"outside")
    try:
        target.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")

    assert (
        _error_category(
            store.publish_restriction, run_id=RUN_ID, envelope=_envelope()
        )
        == FailureCategory.RAW_ARTIFACT_INVALID
    )
    assert source.read_bytes() == b"outside"


def test_oversized_existing_target_fails_before_allocation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    target = store.resolve_restriction_path(
        run_id=RUN_ID, selected_page_id="1000", target_page_id="1001"
    )
    target.parent.mkdir(parents=True)
    with target.open("wb") as stream:
        stream.seek(16 * 1024 * 1024)
        stream.write(b"x")

    assert (
        _error_category(
            store.publish_restriction, run_id=RUN_ID, envelope=_envelope()
        )
        == FailureCategory.RAW_ARTIFACT_INVALID
    )


def test_fsync_failure_does_not_publish_target(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("synthetic fsync failure")

    monkeypatch.setattr(store_module.os, "fsync", fail_fsync)

    assert (
        _error_category(
            store.publish_restriction, run_id=RUN_ID, envelope=_envelope()
        )
        == FailureCategory.RAW_PUBLICATION_FAILURE
    )
    target = store.resolve_restriction_path(
        run_id=RUN_ID, selected_page_id="1000", target_page_id="1001"
    )
    assert not target.exists()
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))


def test_concurrent_identical_creators_publish_once_and_reuse_once(
    tmp_path: Path,
) -> None:
    envelope = _envelope()

    def publish():
        return _store(tmp_path).publish_restriction(
            run_id=RUN_ID, envelope=envelope
        ).outcome

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(lambda _item: publish(), range(2)))

    assert outcomes == [
        ConfluenceRawRestrictionPublicationOutcome.PUBLISHED,
        ConfluenceRawRestrictionPublicationOutcome.REUSED,
    ]


def test_concurrent_different_creators_have_one_conflict(tmp_path: Path) -> None:
    envelopes = (_envelope(body=b"one"), _envelope(body=b"two"))

    def publish(envelope):
        try:
            return _store(tmp_path).publish_restriction(
                run_id=RUN_ID, envelope=envelope
            ).outcome
        except ConfluenceRawRestrictionStoreError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(publish, envelopes))

    assert sorted(outcomes, key=str) == sorted(
        [
            ConfluenceRawRestrictionPublicationOutcome.PUBLISHED,
            FailureCategory.RAW_REPLAY_CONFLICT,
        ],
        key=str,
    )


def test_sanitized_result_and_error_output(tmp_path: Path) -> None:
    store = _store(tmp_path)
    envelope = _envelope(body=b"secret-body")
    result = store.publish_restriction(run_id=RUN_ID, envelope=envelope)

    rendered = repr(result)
    assert "secret-body" not in rendered
    assert str(RUN_ID) not in rendered
    assert str(result.path) not in rendered
    assert result.raw_sha256 not in rendered

    with pytest.raises(ConfluenceRawRestrictionStoreError) as exc_info:
        store.publish_restriction(run_id=RUN_ID, envelope=_envelope(body=b"other"))
    assert str(exc_info.value) == FailureCategory.RAW_REPLAY_CONFLICT
    assert "secret-body" not in repr(exc_info.value)
