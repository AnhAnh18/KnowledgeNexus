from __future__ import annotations

import inspect

import pytest

from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointFailureCategory,
    CheckpointSchemaState,
    CheckpointStateError,
)


def test_safe_schema_dto_and_error_surface() -> None:
    assert CheckpointSchemaState(1).schema_version == 1
    error = CheckpointStateError()
    assert str(error) == "checkpoint_failure"
    assert repr(error) == "CheckpointStateError('checkpoint_failure')"
    assert error.args == ("checkpoint_failure",)
    assert error.category is CheckpointFailureCategory.CHECKPOINT_FAILURE
    assert not hasattr(error, "path")
    assert not hasattr(error, "connection")
    assert not any(name in inspect.signature(CheckpointStateError).parameters for name in ("message", "cause"))


@pytest.mark.parametrize("version", [-1, True, "1", None])
def test_invalid_schema_version_is_sanitized(version) -> None:
    with pytest.raises(CheckpointStateError) as caught:
        CheckpointSchemaState(version)
    assert str(caught.value) == "checkpoint_failure"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
