from __future__ import annotations

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from knowledgenexus.foundation.infrastructure.sidecars import (
    CAPTURED_M6B_EVIDENCE_KIND,
    MAX_RESTRICTION_SIDECAR_BYTES,
    RESTRICTION_SIDECAR_FORMAT_VERSION,
    PreparedRestrictionSidecarTarget,
    RestrictionSidecarPublicationError,
    RestrictionSidecarSerializationError,
    RestrictionSidecarTargetError,
    prepare_restriction_sidecar_target,
    publish_restriction_sidecar,
    serialize_restriction_observations,
)
from knowledgenexus.foundation.infrastructure.sidecars import (
    confluence_restriction_observation_sidecar as sidecar,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]

OBSERVATIONS = (
    {
        "source_page_id": "900",
        "http_status": 200,
        "classification": "restricted",
        "users": [{"userKey": "first"}, {"userKey": "second"}],
        "groups": [{"name": "group-b"}, {"name": "group-a"}],
    },
    {
        "source_page_id": "1000",
        "http_status": 404,
        "classification": "unavailable",
        "users": [],
        "groups": [],
    },
)


def _prepare(target: Path) -> PreparedRestrictionSidecarTarget:
    return prepare_restriction_sidecar_target(
        target_path=target,
        repository_root=REPOSITORY_ROOT,
    )


def test_serialization_is_exact_deterministic_utf8_and_order_preserving() -> None:
    rendered = serialize_restriction_observations(OBSERVATIONS)

    assert rendered == serialize_restriction_observations(OBSERVATIONS)
    assert rendered.endswith(b"\n")
    assert not rendered.startswith(b"\xef\xbb\xbf")
    payload = json.loads(rendered)
    assert list(payload) == [
        "evidence_kind",
        "format_version",
        "restriction_observations",
    ]
    assert payload["format_version"] == RESTRICTION_SIDECAR_FORMAT_VERSION
    assert payload["evidence_kind"] == CAPTURED_M6B_EVIDENCE_KIND
    assert [
        item["source_page_id"] for item in payload["restriction_observations"]
    ] == ["900", "1000"]
    assert payload["restriction_observations"][0]["users"] == [
        {"userKey": "first"},
        {"userKey": "second"},
    ]
    assert payload["restriction_observations"][0]["groups"] == [
        {"name": "group-b"},
        {"name": "group-a"},
    ]


def test_serialization_does_not_mutate_observations() -> None:
    before = json.loads(json.dumps(OBSERVATIONS))

    serialize_restriction_observations(OBSERVATIONS)

    assert json.loads(json.dumps(OBSERVATIONS)) == before


def test_serialization_emits_unicode_as_utf8_without_ascii_escaping() -> None:
    observations = (
        {
            "source_page_id": "1000",
            "http_status": 200,
            "classification": "restricted",
            "users": [{"userKey": "người-dùng"}],
            "groups": [],
        },
    )

    rendered = serialize_restriction_observations(observations)

    assert "người-dùng".encode("utf-8") in rendered
    assert b"\\u" not in rendered


@pytest.mark.parametrize(
    "observations",
    [
        "not-a-sequence",
        b"not-a-sequence",
        ({"source_page_id": float("nan")},),
        ({"source_page_id": object()},),
        (["not-an-object"],),
    ],
)
def test_serialization_fails_with_sanitized_category(
    observations: object,
) -> None:
    with pytest.raises(
        RestrictionSidecarSerializationError,
        match="^sidecar_serialization$",
    ):
        serialize_restriction_observations(observations)  # type: ignore[arg-type]


def test_serialization_enforces_exact_final_byte_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered = serialize_restriction_observations(())
    monkeypatch.setattr(sidecar, "MAX_RESTRICTION_SIDECAR_BYTES", len(rendered))
    assert serialize_restriction_observations(()) == rendered

    monkeypatch.setattr(
        sidecar, "MAX_RESTRICTION_SIDECAR_BYTES", len(rendered) - 1
    )
    with pytest.raises(RestrictionSidecarSerializationError):
        serialize_restriction_observations(())


def test_declared_size_bound_is_sixteen_mib() -> None:
    assert MAX_RESTRICTION_SIDECAR_BYTES == 16 * 1024 * 1024


def test_valid_external_target_prepares_without_creating_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "restriction-observations.json"

    prepared = _prepare(target)

    assert prepared.target_path == target.resolve(strict=False)
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_prepared_target_repr_does_not_disclose_path(tmp_path: Path) -> None:
    target = tmp_path / "private-sidecar-name.json"

    prepared = _prepare(target)

    assert str(target) not in repr(prepared)
    assert target.name not in repr(prepared)


def test_prepared_target_cannot_be_constructed_without_preflight(
    tmp_path: Path,
) -> None:
    with pytest.raises(TypeError):
        PreparedRestrictionSidecarTarget(  # type: ignore[call-arg]
            target_path=tmp_path / "sidecar.json",
            repository_root=REPOSITORY_ROOT,
        )


@pytest.mark.parametrize(
    "target_factory",
    [
        lambda tmp: Path("relative.json"),
        lambda tmp: tmp / "missing" / "sidecar.json",
    ],
    ids=("relative", "missing-parent"),
)
def test_invalid_target_shapes_fail_without_creating_anything(
    tmp_path: Path,
    target_factory: object,
) -> None:
    target = target_factory(tmp_path)  # type: ignore[operator]

    with pytest.raises(RestrictionSidecarTargetError, match="^sidecar_target$"):
        _prepare(target)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows path-form validation")
@pytest.mark.parametrize(
    "target",
    [
        Path(r"\\fixture.invalid\share\sidecar.json"),
        Path(r"C:\temp\sidecar.json:stream"),
        Path(r"C:\temp\CON.json"),
        Path("C:\\temp\\trailing-dot."),
    ],
)
def test_unsupported_windows_path_forms_are_rejected(target: Path) -> None:
    with pytest.raises(RestrictionSidecarTargetError):
        prepare_restriction_sidecar_target(
            target_path=target,
            repository_root=REPOSITORY_ROOT,
        )


def test_repository_internal_target_is_rejected() -> None:
    target = REPOSITORY_ROOT / ".m6f-c1-forbidden-sidecar.json"

    with pytest.raises(RestrictionSidecarTargetError):
        _prepare(target)

    assert not target.exists()


def test_existing_target_is_rejected_and_unchanged(tmp_path: Path) -> None:
    target = tmp_path / "sidecar.json"
    target.write_text("foreign", encoding="utf-8")

    with pytest.raises(RestrictionSidecarTargetError):
        _prepare(target)

    assert target.read_text(encoding="utf-8") == "foreign"


def test_non_directory_parent_is_rejected(tmp_path: Path) -> None:
    parent = tmp_path / "not-a-directory"
    parent.write_text("foreign", encoding="utf-8")

    with pytest.raises(RestrictionSidecarTargetError):
        _prepare(parent / "sidecar.json")


def test_unresolved_repository_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RestrictionSidecarTargetError):
        prepare_restriction_sidecar_target(
            target_path=tmp_path / "sidecar.json",
            repository_root=tmp_path / "missing-repository",
        )


def test_dangling_target_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "sidecar.json"
    try:
        target.symlink_to(tmp_path / "missing-target")
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(RestrictionSidecarTargetError):
        _prepare(target)


def test_symlinked_parent_is_rejected(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(RestrictionSidecarTargetError):
        _prepare(linked_parent / "sidecar.json")


def test_reparse_parent_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_lstat = sidecar.os.lstat

    def mark_parent_as_reparse(path: object) -> object:
        details = real_lstat(path)
        if Path(path) == tmp_path:
            return SimpleNamespace(
                st_mode=details.st_mode,
                st_file_attributes=sidecar._FILE_ATTRIBUTE_REPARSE_POINT,
            )
        return details

    monkeypatch.setattr(sidecar.os, "lstat", mark_parent_as_reparse)

    with pytest.raises(RestrictionSidecarTargetError):
        _prepare(tmp_path / "sidecar.json")


def test_publish_writes_exact_bytes_and_removes_temp(tmp_path: Path) -> None:
    target = tmp_path / "sidecar.json"
    prepared = _prepare(target)
    content = serialize_restriction_observations(OBSERVATIONS)

    publish_restriction_sidecar(prepared_target=prepared, content=content)

    assert target.read_bytes() == content
    assert list(tmp_path.iterdir()) == [target]


def test_publish_rejects_oversized_bytes_before_creating_temp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "sidecar.json"
    prepared = _prepare(target)
    monkeypatch.setattr(sidecar, "MAX_RESTRICTION_SIDECAR_BYTES", 3)

    with pytest.raises(RestrictionSidecarSerializationError):
        publish_restriction_sidecar(
            prepared_target=prepared,
            content=b"four",
        )

    assert list(tmp_path.iterdir()) == []


def test_target_appearing_after_preflight_is_never_overwritten(
    tmp_path: Path,
) -> None:
    target = tmp_path / "sidecar.json"
    prepared = _prepare(target)
    target.write_text("foreign", encoding="utf-8")

    with pytest.raises(
        RestrictionSidecarPublicationError,
        match="^sidecar_publication$",
    ):
        publish_restriction_sidecar(
            prepared_target=prepared,
            content=b"ours\n",
        )

    assert target.read_text(encoding="utf-8") == "foreign"
    assert list(tmp_path.iterdir()) == [target]


def test_write_failure_leaves_no_final_or_temporary_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "sidecar.json"
    prepared = _prepare(target)

    def fail_fsync(descriptor: int) -> None:
        raise OSError("synthetic write failure")

    monkeypatch.setattr(sidecar.os, "fsync", fail_fsync)

    with pytest.raises(RestrictionSidecarPublicationError):
        publish_restriction_sidecar(
            prepared_target=prepared,
            content=b"content\n",
        )

    assert list(tmp_path.iterdir()) == []


def test_link_failure_leaves_no_final_or_temporary_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "sidecar.json"
    prepared = _prepare(target)

    def fail_link(source: object, destination: object) -> None:
        raise OSError("synthetic link failure")

    monkeypatch.setattr(sidecar.os, "link", fail_link)

    with pytest.raises(RestrictionSidecarPublicationError):
        publish_restriction_sidecar(
            prepared_target=prepared,
            content=b"content\n",
        )

    assert list(tmp_path.iterdir()) == []


def test_concurrent_publishers_produce_exactly_one_success(
    tmp_path: Path,
) -> None:
    target = tmp_path / "sidecar.json"
    prepared = _prepare(target)
    content = serialize_restriction_observations(OBSERVATIONS)

    def publish() -> bool:
        try:
            publish_restriction_sidecar(
                prepared_target=prepared,
                content=content,
            )
        except RestrictionSidecarPublicationError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as executor:
        successes = list(executor.map(lambda _index: publish(), range(8)))

    assert successes.count(True) == 1
    assert target.read_bytes() == content
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission assertion")
def test_published_file_retains_user_restrictive_temp_permissions(
    tmp_path: Path,
) -> None:
    target = tmp_path / "sidecar.json"

    publish_restriction_sidecar(
        prepared_target=_prepare(target),
        content=b"content\n",
    )

    assert stat.S_IMODE(target.stat().st_mode) == 0o600
