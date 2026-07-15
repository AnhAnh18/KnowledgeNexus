from __future__ import annotations

from tests.fixtures.foundation.record_factories import (
    build_sample_acl_record,
    build_sample_chunk_record,
    build_sample_document_record,
    build_sample_relation_record,
)


def build_sample_record_set() -> dict[str, list[dict[str, object]]]:
    return {
        "documents": [build_sample_document_record()],
        "chunks": [build_sample_chunk_record()],
        "relations": [build_sample_relation_record()],
        "acl_records": [build_sample_acl_record()],
    }
