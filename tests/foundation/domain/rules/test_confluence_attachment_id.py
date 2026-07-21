from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.rules.confluence_attachment_id import (
    require_confluence_attachment_id,
)


@pytest.mark.parametrize("value", ["1", "2000", "att1", "att2000"])
def test_accepts_documented_data_center_attachment_id_shapes(value: str) -> None:
    assert require_confluence_attachment_id(value) == value


@pytest.mark.parametrize(
    "value",
    ["", "att", "ATT1", "att-1", "att1x", "-1", " 1", "1 ", "１"],
)
def test_rejects_non_attachment_id_strings(value: str) -> None:
    with pytest.raises(ValueError):
        require_confluence_attachment_id(value)


@pytest.mark.parametrize("value", [None, True, 1, b"att1"])
def test_rejects_non_string_values(value: object) -> None:
    with pytest.raises(TypeError):
        require_confluence_attachment_id(value)
