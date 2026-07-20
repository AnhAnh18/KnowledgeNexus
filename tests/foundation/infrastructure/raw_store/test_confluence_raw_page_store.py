from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.raw_page_artifact import RawPageArtifact
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluenceRawPageStore,
    ConfluenceRawPageStoreError,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    confluence_raw_page_store as store_module,
)
from knowledgenexus.foundation.ports.raw_page_store_port import RawPageStoreError


PAGE_ID = "1000"
# Deliberately awkward bytes: unicode escape, double spaces, embedded newline,
# key order that is not sorted, and trailing bytes after the closing brace.
RAW = (
    '{"id":"1000","title":"T\\u00e9st  ","body":'
    '{"storage":{"value":"<p>a  b</p>\\n"}},"z":1,"a":2}  \n'
).encode("utf-8")


def _store(root: Path) -> ConfluenceRawPageStore:
    return ConfluenceRawPageStore(raw_root=root)


def test_deterministic_path_is_root_confluence_pages_pageid_json(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)

    path = store.resolve_path(page_id=PAGE_ID)

    assert path == (tmp_path.resolve() / "confluence" / "pages" / "1000.json")
    # Same root + page id always resolves to the same final path.
    assert store.resolve_path(page_id=PAGE_ID) == path


def test_write_persists_exact_bytes_without_reserialization(
    tmp_path: Path,
) -> None:
    artifact = _store(tmp_path).write(page_id=PAGE_ID, raw_bytes=RAW)

    assert isinstance(artifact, RawPageArtifact)
    on_disk = artifact.path.read_bytes()
    assert on_disk == RAW  # byte-for-byte, no sort/pretty/compact/normalize
    assert artifact.byte_count == len(RAW)


def test_raw_sha256_matches_hashlib_over_exact_bytes(tmp_path: Path) -> None:
    artifact = _store(tmp_path).write(page_id=PAGE_ID, raw_bytes=RAW)

    assert artifact.raw_sha256 == hashlib.sha256(RAW).hexdigest()
    assert artifact.raw_sha256 == hashlib.sha256(
        artifact.path.read_bytes()
    ).hexdigest()


def test_success_atomically_replaces_an_existing_target(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.write(page_id=PAGE_ID, raw_bytes=b'{"id":"1000","v":1}')
    old_bytes = first.path.read_bytes()

    second = store.write(page_id=PAGE_ID, raw_bytes=RAW)

    assert second.path == first.path
    assert second.path.read_bytes() == RAW != old_bytes
    # No leftover temporary files in the pages directory.
    assert sorted(p.name for p in second.path.parent.iterdir()) == ["1000.json"]


@pytest.mark.parametrize(
    "page_id",
    ["../secret", "1000/../../etc", "a1000", "", "10.0", "10 0", "1000\n"],
)
def test_unsafe_page_id_is_rejected_before_any_write(
    tmp_path: Path, page_id: str
) -> None:
    with pytest.raises((ValueError, ConfluenceRawPageStoreError)):
        _store(tmp_path).write(page_id=page_id, raw_bytes=RAW)

    assert not (tmp_path / "confluence").exists()


def test_write_failure_leaves_no_partial_final_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(fd: int) -> None:
        raise OSError("disk full during fsync")

    monkeypatch.setattr(store_module.os, "fsync", boom)

    with pytest.raises(ConfluenceRawPageStoreError):
        _store(tmp_path).write(page_id=PAGE_ID, raw_bytes=RAW)

    target = tmp_path / "confluence" / "pages" / "1000.json"
    assert not target.exists()
    # The temporary is cleaned; the directory holds nothing.
    assert list(target.parent.iterdir()) == []


def test_replace_failure_preserves_prior_final_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    prior = store.write(page_id=PAGE_ID, raw_bytes=b'{"id":"1000","prior":true}')
    prior_bytes = prior.path.read_bytes()

    def boom(src: object, dst: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(store_module.os, "replace", boom)

    with pytest.raises(ConfluenceRawPageStoreError):
        store.write(page_id=PAGE_ID, raw_bytes=RAW)

    assert prior.path.read_bytes() == prior_bytes  # unchanged
    # Only the prior final file remains; the temp was cleaned.
    assert sorted(p.name for p in prior.path.parent.iterdir()) == ["1000.json"]


def test_cleanup_never_deletes_unrelated_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pages = tmp_path / "confluence" / "pages"
    pages.mkdir(parents=True)
    bystander = pages / "9999.json"
    bystander.write_bytes(b"unrelated")

    def boom(fd: int) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr(store_module.os, "fsync", boom)

    with pytest.raises(ConfluenceRawPageStoreError):
        _store(tmp_path).write(page_id=PAGE_ID, raw_bytes=RAW)

    assert bystander.read_bytes() == b"unrelated"
    assert not (pages / "1000.json").exists()


def test_empty_body_is_persisted_and_hashed(tmp_path: Path) -> None:
    artifact = _store(tmp_path).write(page_id=PAGE_ID, raw_bytes=b"")

    assert artifact.path.read_bytes() == b""
    assert artifact.byte_count == 0
    assert artifact.raw_sha256 == hashlib.sha256(b"").hexdigest()


def test_non_bytes_body_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="raw_bytes expects bytes"):
        _store(tmp_path).write(page_id=PAGE_ID, raw_bytes="not bytes")  # type: ignore[arg-type]


def test_store_error_is_a_port_error(tmp_path: Path) -> None:
    # The use case catches the port-level RawPageStoreError, so the concrete
    # store error must be a subclass of it.
    assert issubclass(ConfluenceRawPageStoreError, RawPageStoreError)
