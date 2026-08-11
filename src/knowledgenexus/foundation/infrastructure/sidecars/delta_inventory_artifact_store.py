from __future__ import annotations

import os
import tempfile
from pathlib import Path

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.delta_inventory import DeltaInventoryEnvelope
from knowledgenexus.foundation.ports.path_safety import require_plain_directory_chain, require_plain_file

_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024


def _bounded_read(path: Path) -> bytes:
    require_plain_file(path)
    with path.open("rb") as handle:
        content = handle.read(_MAX_ARTIFACT_BYTES + 1)
    require_plain_file(path)
    if len(content) > _MAX_ARTIFACT_BYTES:
        raise DeltaInventoryArtifactStoreError("artifact_too_large")
    return content


class DeltaInventoryArtifactStoreError(ValueError):
    """Sanitized failure for generation-scoped delta inventory artifacts."""


class DeltaInventoryArtifactStore:
    """Atomic, no-clobber storage for one generation's derived inventory."""

    def __init__(self, *, state_root: Path) -> None:
        if type(state_root) is not Path or not state_root.is_absolute():
            raise DeltaInventoryArtifactStoreError("invalid_artifact_path")
        try:
            require_plain_directory_chain(state_root)
        except Exception:
            raise DeltaInventoryArtifactStoreError("invalid_artifact_path") from None
        self._state_root = state_root

    def resolve_path(self, *, generation_id: CrawlRunId) -> Path:
        if type(generation_id) is not CrawlRunId:
            raise DeltaInventoryArtifactStoreError("invalid_identity")
        try:
            generation_id = CrawlRunId(generation_id.value)
        except Exception:
            raise DeltaInventoryArtifactStoreError("invalid_identity") from None
        path = self._state_root / str(generation_id) / "delta-inventory.json"
        try:
            path.relative_to(self._state_root)
        except ValueError:
            raise DeltaInventoryArtifactStoreError("invalid_artifact_path") from None
        return path

    def publish(self, *, envelope: DeltaInventoryEnvelope) -> Path:
        if type(envelope) is not DeltaInventoryEnvelope:
            raise DeltaInventoryArtifactStoreError("invalid_envelope")
        target = self.resolve_path(generation_id=envelope.generation_id)
        content = envelope.to_bytes()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            require_plain_directory_chain(target.parent)
            if target.exists() or target.is_symlink():
                if target.is_symlink():
                    raise DeltaInventoryArtifactStoreError("unsafe_target")
                require_plain_file(target)
                if target.stat().st_size > _MAX_ARTIFACT_BYTES:
                    raise DeltaInventoryArtifactStoreError("artifact_too_large")
                existing = _bounded_read(target)
                if existing != content:
                    raise DeltaInventoryArtifactStoreError("replay_conflict")
                return target
            with tempfile.NamedTemporaryFile("wb", dir=target.parent, prefix=".delta-inventory.", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                if target.is_symlink():
                    raise DeltaInventoryArtifactStoreError("unsafe_target")
                require_plain_file(target)
                if target.stat().st_size > _MAX_ARTIFACT_BYTES:
                    raise DeltaInventoryArtifactStoreError("artifact_too_large")
                if _bounded_read(target) != content:
                    raise DeltaInventoryArtifactStoreError("replay_conflict")
            finally:
                temporary.unlink(missing_ok=True)
            require_plain_file(target)
            if target.stat().st_size > _MAX_ARTIFACT_BYTES or _bounded_read(target) != content:
                raise DeltaInventoryArtifactStoreError("publication_failed")
            return target
        except DeltaInventoryArtifactStoreError:
            raise
        except (OSError, ValueError, TypeError):
            raise DeltaInventoryArtifactStoreError("publication_failed") from None

    def read(self, *, generation_id: CrawlRunId) -> DeltaInventoryEnvelope:
        target = self.resolve_path(generation_id=generation_id)
        try:
            require_plain_file(target)
            if target.stat().st_size > _MAX_ARTIFACT_BYTES:
                raise ValueError
            return DeltaInventoryEnvelope.from_bytes(_bounded_read(target))
        except Exception:
            raise DeltaInventoryArtifactStoreError("artifact_invalid") from None


__all__ = ["DeltaInventoryArtifactStore", "DeltaInventoryArtifactStoreError"]
