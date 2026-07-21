from __future__ import annotations

from pathlib import Path

from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluencePageObservationStore,
    ConfluenceRawPageStore,
)


def test_production_m6a_store_path_is_read_by_production_m6b_store(
    tmp_path: Path,
) -> None:
    raw = b'{"id":"1000","ancestors":[]}  \n'

    artifact = ConfluenceRawPageStore(raw_root=tmp_path).write(
        page_id="1000",
        raw_bytes=raw,
    )
    observed = ConfluencePageObservationStore(raw_root=tmp_path).read_page(
        page_id="1000"
    )

    assert artifact.path == (
        tmp_path.resolve() / "confluence" / "pages" / "1000.json"
    )
    assert observed == raw
