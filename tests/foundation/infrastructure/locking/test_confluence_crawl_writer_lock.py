from __future__ import annotations

import copy
import os

import pytest

from knowledgenexus.foundation.infrastructure.locking import (
    confluence_crawl_writer_lock as module,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointStateError,
)


def test_locking_package_is_non_public() -> None:
    import knowledgenexus.foundation.infrastructure.locking as package

    assert package.__all__ == []
    assert not hasattr(package, "WriterLockLease")


def test_writer_lock_rejects_path_subclass_before_derivation(tmp_path) -> None:
    outside = tmp_path.parent / "writer-lock-outside"

    class RedirectingPath(type(tmp_path)):
        def __truediv__(self, child):
            return outside / child

    with pytest.raises(CheckpointStateError):
        module._acquire_writer_lock(RedirectingPath(tmp_path))
    assert not outside.exists()


def test_writer_lock_preserves_existing_bytes(tmp_path) -> None:
    lock = tmp_path / module.LOCK_NAME
    lock.write_bytes(b"opaque bytes")
    before = (lock.read_bytes(), lock.stat().st_ino, lock.stat().st_size)
    lease = module._acquire_writer_lock(tmp_path)
    try:
        lease._verify()
    finally:
        lease.close()
    after = (lock.read_bytes(), lock.stat().st_ino, lock.stat().st_size)
    assert after == before


def test_writer_lock_rejects_preexisting_sidecar_deletion(tmp_path) -> None:
    sidecar = tmp_path / (module.DB_NAME + "-journal")
    sidecar.write_bytes(b"pre-existing journal")
    lease = module._acquire_writer_lock(tmp_path)
    try:
        sidecar.unlink()
        with pytest.raises(CheckpointStateError):
            lease._verify()
    finally:
        lease.close()


def test_writer_lock_rejects_same_inode_ancestor_metadata_change(tmp_path) -> None:
    lease = module._acquire_writer_lock(tmp_path)
    try:
        ancestor = tmp_path.parent
        info = ancestor.stat()
        os.utime(ancestor, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
        with pytest.raises(CheckpointStateError):
            lease._verify()
    finally:
        lease.close()


def test_writer_lock_rejects_same_inode_sidecar_metadata_change(tmp_path) -> None:
    sidecar = tmp_path / (module.DB_NAME + "-journal")
    sidecar.write_bytes(b"pre-existing journal")
    lease = module._acquire_writer_lock(tmp_path)
    try:
        info = sidecar.stat()
        os.utime(sidecar, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
        with pytest.raises(CheckpointStateError):
            lease._verify()
    finally:
        lease.close()


def test_writer_lock_rejects_dangling_derived_symlink(tmp_path) -> None:
    try:
        (tmp_path / module.DB_NAME).symlink_to(tmp_path / "missing")
    except OSError:
        pytest.skip("symlink capability unavailable")
    with pytest.raises(CheckpointStateError):
        module._acquire_writer_lock(tmp_path)


@pytest.mark.parametrize("copier", [copy.copy, copy.deepcopy])
def test_writer_lock_lease_cannot_be_copied(tmp_path, copier) -> None:
    lease = module._acquire_writer_lock(tmp_path)
    try:
        with pytest.raises(CheckpointStateError):
            copier(lease)
        lease._verify()
    finally:
        lease.close()
