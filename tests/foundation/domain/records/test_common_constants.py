from __future__ import annotations

from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION


def test_common_record_schema_version_is_contract_version() -> None:
    assert SCHEMA_VERSION == "1.0"
