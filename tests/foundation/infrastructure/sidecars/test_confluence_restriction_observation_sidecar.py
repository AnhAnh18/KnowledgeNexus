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
    SYNTHETIC_FIXTURE_EVIDENCE_KIND,
    LoadedRestrictionSidecar,
    PreparedRestrictionSidecarTarget,
    RestrictionSidecarLoadError,
    RestrictionSidecarPublicationError,
    RestrictionSidecarSerializationError,
    RestrictionSidecarTargetError,
    load_restriction_sidecar,
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


def _write_loaded_sidecar(
    path: Path,
    *,
    evidence_kind: str = CAPTURED_M6B_EVIDENCE_KIND,
    observations: object = OBSERVATIONS,
) -> bytes:
    content = (
        json.dumps(
            {
                "format_version": RESTRICTION_SIDECAR_FORMAT_VERSION,
                "evidence_kind": evidence_kind,
                "restriction_observations": observations,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    path.write_bytes(content)
    return content


@pytest.mark.parametrize(
    "evidence_kind",
    [CAPTURED_M6B_EVIDENCE_KIND, SYNTHETIC_FIXTURE_EVIDENCE_KIND],
)
def test_strict_loader_accepts_both_evidence_kinds_and_preserves_order(
    tmp_path: Path,
    evidence_kind: str,
) -> None:
    target = tmp_path / "sidecar.json"
    exact = _write_loaded_sidecar(target, evidence_kind=evidence_kind)

    loaded, source_bytes = load_restriction_sidecar(target)

    assert isinstance(loaded, LoadedRestrictionSidecar)
    assert loaded.evidence_kind == evidence_kind
    assert source_bytes == exact
    assert [
        item["source_page_id"]  # type: ignore[index]
        for item in loaded.restriction_observations
    ] == ["900", "1000"]


def test_loaded_sidecar_is_ownership_isolated_and_repr_safe(
    tmp_path: Path,
) -> None:
    target = tmp_path / "private-sidecar-name.json"
    _write_loaded_sidecar(target)

    loaded, _ = load_restriction_sidecar(target)
    payload = loaded.restriction_observations[0]
    assert isinstance(payload, dict)
    payload["source_page_id"] = "changed"
    reloaded, _ = load_restriction_sidecar(target)

    assert (
        reloaded.restriction_observations[0]["source_page_id"]  # type: ignore[index]
        == "900"
    )
    assert target.name not in repr(loaded)
    assert "900" not in repr(loaded)


def test_strict_loader_accepts_exact_byte_cap_and_rejects_cap_plus_one(
    tmp_path: Path,
) -> None:
    prefix = (
        b'{"evidence_kind":"synthetic_fixture","format_version":"1.0",'
        b'"restriction_observations":["'
    )
    suffix = b'"]}'
    content = (
        prefix
        + (
            b"x"
            * (
                MAX_RESTRICTION_SIDECAR_BYTES
                - len(prefix)
                - len(suffix)
            )
        )
        + suffix
    )
    target = tmp_path / "sidecar.json"
    target.write_bytes(content)

    assert load_restriction_sidecar(target)[1] == content

    target.write_bytes(content + b" ")
    with pytest.raises(RestrictionSidecarLoadError):
        load_restriction_sidecar(target)


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"\xef\xbb\xbf{}",
        b"\xff",
        b"{",
        b"[]",
        b'{"format_version":"1.0","evidence_kind":"captured_m6b_result"}',
        (
            b'{"format_version":"1.0","evidence_kind":"captured_m6b_result",'
            b'"restriction_observations":[],"extra":true}'
        ),
        (
            b'{"format_version":"2.0","evidence_kind":"captured_m6b_result",'
            b'"restriction_observations":[]}'
        ),
        (
            b'{"format_version":"1.0","evidence_kind":"unknown",'
            b'"restriction_observations":[]}'
        ),
        (
            b'{"format_version":"1.0","evidence_kind":"captured_m6b_result",'
            b'"restriction_observations":{}}'
        ),
        (
            b'{"format_version":"1.0","format_version":"1.0",'
            b'"evidence_kind":"captured_m6b_result","restriction_observations":[]}'
        ),
        (
            b'{"format_version":"1.0","evidence_kind":"captured_m6b_result",'
            b'"restriction_observations":[{"users":[{"userKey":"a",'
            b'"userKey":"b"}]}]}'
        ),
        (
            b'{"format_version":"1.0","evidence_kind":"captured_m6b_result",'
            b'"restriction_observations":[NaN]}'
        ),
        (
            b'{"format_version":"1.0","evidence_kind":"captured_m6b_result",'
            b'"restriction_observations":[Infinity]}'
        ),
    ],
)
def test_strict_loader_rejects_invalid_bytes_with_sanitized_failure(
    tmp_path: Path,
    content: bytes,
) -> None:
    target = tmp_path / "sensitive-name.json"
    target.write_bytes(content)

    with pytest.raises(
        RestrictionSidecarLoadError, match="^restriction_sidecar$"
    ) as captured:
        load_restriction_sidecar(target)

    assert target.name not in repr(captured.value)
    assert "userKey" not in repr(captured.value)


@pytest.mark.parametrize("number", ("1e309", "-1e309", "1e999999"))
def test_strict_loader_rejects_nested_exponent_overflow_as_non_finite(
    tmp_path: Path,
    number: str,
) -> None:
    target = tmp_path / "sensitive-name.json"
    target.write_bytes(
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

    with pytest.raises(
        RestrictionSidecarLoadError,
        match="^restriction_sidecar$",
    ) as captured:
        load_restriction_sidecar(target)

    assert target.name not in repr(captured.value)
    assert number not in repr(captured.value)


def test_strict_loader_rejects_missing_directory_and_relative_paths(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()
    for path in (
        tmp_path / "missing.json",
        directory,
        Path("relative.json"),
    ):
        with pytest.raises(RestrictionSidecarLoadError):
            load_restriction_sidecar(path)


def test_strict_loader_rejects_symlink_and_symlink_parent(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real.json"
    _write_loaded_sidecar(real)
    linked = tmp_path / "linked.json"
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    nested = real_parent / "nested.json"
    _write_loaded_sidecar(nested)
    linked_parent = tmp_path / "linked-parent"
    try:
        linked.symlink_to(real)
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(RestrictionSidecarLoadError):
        load_restriction_sidecar(linked)
    with pytest.raises(RestrictionSidecarLoadError):
        load_restriction_sidecar(linked_parent / "nested.json")


def test_strict_loader_rejects_path_identity_change_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "sidecar.json"
    _write_loaded_sidecar(target)
    calls = 0
    if os.name == "nt":
        real_stat = sidecar._stat_windows_bound_entry

        def changed_identity(
            *,
            parent_handle: int,
            name: str,
        ) -> object:
            nonlocal calls
            details = real_stat(
                parent_handle=parent_handle,
                name=name,
            )
            calls += 1
            if calls == 1:
                return details
            return SimpleNamespace(
                st_dev=details.st_dev,
                st_ino=details.st_ino + 1,
                st_size=details.st_size,
                st_mtime_ns=details.st_mtime_ns,
                st_mode=details.st_mode,
                st_file_attributes=getattr(
                    details,
                    "st_file_attributes",
                    0,
                ),
            )

        monkeypatch.setattr(
            sidecar,
            "_stat_windows_bound_entry",
            changed_identity,
        )
    else:
        real_stat = sidecar._stat_posix_bound_entry

        def changed_identity(
            *,
            parent_descriptor: int,
            name: str,
        ) -> object:
            nonlocal calls
            details = real_stat(
                parent_descriptor=parent_descriptor,
                name=name,
            )
            calls += 1
            if calls == 1:
                return details
            return SimpleNamespace(
                st_dev=details.st_dev,
                st_ino=details.st_ino + 1,
                st_size=details.st_size,
                st_mtime_ns=details.st_mtime_ns,
                st_mode=details.st_mode,
                st_file_attributes=getattr(
                    details,
                    "st_file_attributes",
                    0,
                ),
            )

        monkeypatch.setattr(
            sidecar,
            "_stat_posix_bound_entry",
            changed_identity,
        )

    with pytest.raises(RestrictionSidecarLoadError):
        load_restriction_sidecar(target)


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-relative race")
def test_strict_loader_does_not_follow_parent_swap_after_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    safe_parent = tmp_path / "safe-parent"
    safe_parent.mkdir()
    target = safe_parent / "sidecar.json"
    expected = _write_loaded_sidecar(target)
    moved_safe_parent = tmp_path / "moved-safe-parent"
    attacker_parent = tmp_path / "attacker-parent"
    attacker_parent.mkdir()
    attacker_target = attacker_parent / target.name
    attacker_target.write_bytes(
        expected.replace(b'"900"', b'"777"', 1)
    )
    real_stat = sidecar._stat_posix_bound_entry
    swapped = False

    def swap_then_stat(
        *,
        parent_descriptor: int,
        name: str,
    ) -> os.stat_result:
        nonlocal swapped
        if not swapped:
            safe_parent.rename(moved_safe_parent)
            safe_parent.symlink_to(attacker_parent, target_is_directory=True)
            swapped = True
        return real_stat(
            parent_descriptor=parent_descriptor,
            name=name,
        )

    monkeypatch.setattr(
        sidecar,
        "_stat_posix_bound_entry",
        swap_then_stat,
    )

    loaded, exact_bytes = load_restriction_sidecar(target)

    assert swapped
    assert exact_bytes == expected
    assert loaded.restriction_observations[0]["source_page_id"] == "900"  # type: ignore[index]
    assert target.read_bytes() == attacker_target.read_bytes()


@pytest.mark.skipif(os.name != "nt", reason="Windows parent handle guard")
def test_strict_loader_holds_parent_against_replacement_during_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "guarded-parent"
    parent.mkdir()
    target = parent / "sidecar.json"
    expected = _write_loaded_sidecar(target)
    moved_parent = tmp_path / "moved-parent"
    attacker_parent = tmp_path / "attacker-parent"
    attacker_parent.mkdir()
    attacker_target = attacker_parent / target.name
    attacker_bytes = expected.replace(b'"900"', b'"777"', 1)
    attacker_target.write_bytes(attacker_bytes)
    real_stat = sidecar._stat_windows_bound_entry
    swapped = False

    def swap_then_stat(
        *,
        parent_handle: int,
        name: str,
    ) -> os.stat_result:
        nonlocal swapped
        if not swapped:
            parent.rename(moved_parent)
            attacker_parent.rename(parent)
            swapped = True
        return real_stat(
            parent_handle=parent_handle,
            name=name,
        )

    monkeypatch.setattr(
        sidecar,
        "_stat_windows_bound_entry",
        swap_then_stat,
    )

    assert load_restriction_sidecar(target)[1] == expected
    assert swapped
    assert target.read_bytes() == attacker_bytes
    assert (moved_parent / target.name).read_bytes() == expected
    assert target.exists()
    assert moved_parent.exists()


def test_strict_loader_rejects_reparse_file_attribute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "sidecar.json"
    _write_loaded_sidecar(target)
    if os.name != "nt":
        pytest.skip("Windows reparse attribute assertion")
    real_attributes = sidecar._windows_file_attributes

    def mark_file_as_reparse(handle: int) -> int:
        attributes = real_attributes(handle)
        if attributes & 0x10:  # FILE_ATTRIBUTE_DIRECTORY
            return attributes
        return attributes | sidecar._FILE_ATTRIBUTE_REPARSE_POINT

    monkeypatch.setattr(
        sidecar,
        "_windows_file_attributes",
        mark_file_as_reparse,
    )

    with pytest.raises(RestrictionSidecarLoadError):
        load_restriction_sidecar(target)


def test_strict_loader_sanitizes_open_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "sensitive-sidecar.json"
    _write_loaded_sidecar(target)

    def fail_open(*_args: object, **_kwargs: object) -> object:
        raise OSError("SENSITIVE PATH OR CONTENT")

    if os.name == "nt":
        monkeypatch.setattr(
            sidecar,
            "_open_windows_regular_file_descriptor",
            fail_open,
        )
    else:
        monkeypatch.setattr(
            sidecar,
            "_open_posix_bound_regular_file",
            fail_open,
        )

    with pytest.raises(RestrictionSidecarLoadError) as captured:
        load_restriction_sidecar(target)

    assert "SENSITIVE" not in str(captured.value)
    assert target.name not in repr(captured.value)


def test_existing_c1_serializer_remains_byte_identical_after_loader_added() -> None:
    assert serialize_restriction_observations(OBSERVATIONS) == (
        b'{"evidence_kind":"captured_m6b_result","format_version":"1.0",'
        b'"restriction_observations":[{"classification":"restricted",'
        b'"groups":[{"name":"group-b"},{"name":"group-a"}],"http_status":200,'
        b'"source_page_id":"900","users":[{"userKey":"first"},'
        b'{"userKey":"second"}]},{"classification":"unavailable","groups":[],'
        b'"http_status":404,"source_page_id":"1000","users":[]}]}\n'
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
    load_restriction_sidecar,
