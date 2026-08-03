import pytest

from knowledgenexus.foundation.domain.models import (
    CanonicalIncludeRoots, CrawlRunId, ConfluenceInventoryWindow,
    ConfluencePageMetadata, InventoryOccurrence, InventoryReplayConflict,
    InventoryWindowCommit, replay_equivalent,
)

RUN = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
ROOTS = CanonicalIncludeRoots(("root",))
META = ConfluencePageMetadata("page", "Page", "S", parent_page_id="root", ancestor_page_ids=("root",), ancestor_titles=("Root",))

def _commit(title="Page"):
    metadata = META if title == "Page" else ConfluencePageMetadata("page", title, "S", parent_page_id="root", ancestor_page_ids=("root",), ancestor_titles=("Root",))
    window = ConfluenceInventoryWindow((metadata,), 0, 10, 1, 1)
    occurrence = InventoryOccurrence(RUN, 0, "root", 0, 0, "page", metadata, ROOTS)
    return InventoryWindowCommit(RUN, 0, "root", 0, window, (occurrence,), ROOTS)

def test_occurrence_requires_complete_root_mapping_and_window_matches_items():
    with pytest.raises(ValueError): InventoryOccurrence(RUN, 0, "wrong", 0, 0, "page", META, ROOTS)
    assert _commit().occurrences[0].metadata == _commit().window.items[0]

def test_replay_is_exact_and_uses_sanitized_identity_or_state_categories():
    assert replay_equivalent(_commit(), _commit())
    with pytest.raises(InventoryReplayConflict, match="state_conflict") as state:
        replay_equivalent(_commit(), _commit("Changed"))
    assert "page" not in str(state.value)
    other = InventoryWindowCommit(RUN, 0, "root", 1, ConfluenceInventoryWindow((META,), 1, 10, 1, 2), (InventoryOccurrence(RUN, 0, "root", 1, 0, "page", META, ROOTS),), ROOTS)
    with pytest.raises(InventoryReplayConflict, match="inventory_identity_conflict"):
        replay_equivalent(_commit(), other)
    with pytest.raises(InventoryReplayConflict, match="inventory_identity_conflict"):
        replay_equivalent(_commit(), object())

def test_requested_start_is_exact_and_part_of_commit_identity():
    with pytest.raises(ValueError):
        InventoryWindowCommit(RUN, 0, "root", 1, ConfluenceInventoryWindow((META,), 0, 10, 1, 1), (InventoryOccurrence(RUN, 0, "root", 0, 0, "page", META, ROOTS),), ROOTS)
    with pytest.raises(ValueError): InventoryOccurrence(RUN, 0, "root", 0, 0, "root", ConfluencePageMetadata("root", "Root", "S"), ROOTS)

def test_window_commit_rejects_non_occurrence_without_attribute_error():
    with pytest.raises(ValueError): InventoryWindowCommit(RUN, 0, "root", 0, ConfluenceInventoryWindow((META,), 0, 10, 1, 1), (object(),), ROOTS)
    class Broken:
        def __iter__(self): raise RuntimeError("private")
    with pytest.raises(TypeError): InventoryWindowCommit(RUN, 0, "root", 0, ConfluenceInventoryWindow((META,), 0, 10, 1, 1), Broken(), ROOTS)
    class Boom:
        def __iter__(self): raise RuntimeError("secret")
    broken_window = ConfluenceInventoryWindow((META,), 0, 10, 1, 1)
    object.__setattr__(broken_window, "items", Boom())
    with pytest.raises(ValueError, match="invalid window commit") as error:
        InventoryWindowCommit(RUN, 0, "root", 0, broken_window, (), ROOTS)
    assert "secret" not in str(error.value)

def test_window_commit_rejects_tampered_terminal_derived_facts():
    window = ConfluenceInventoryWindow((META,), 0, 10, 1, 1)
    object.__setattr__(window, "next_start", 1)
    occurrence = InventoryOccurrence(RUN, 0, "root", 0, 0, "page", META, ROOTS)
    with pytest.raises(ValueError): InventoryWindowCommit(RUN, 0, "root", 0, window, (occurrence,), ROOTS)
    metadata = ConfluencePageMetadata("page", "Page", "S", parent_page_id="root", ancestor_page_ids=("root",), ancestor_titles=("Root",))
    object.__setattr__(metadata, "labels", ("z", "a", "z"))
    with pytest.raises(ValueError): InventoryWindowCommit(RUN, 0, "root", 0, ConfluenceInventoryWindow((metadata,), 0, 10, 1, 1), (occurrence,), ROOTS)
    tampered = _commit()
    object.__setattr__(tampered.include_roots, "root_ids", ("root", "root"))
    with pytest.raises(InventoryReplayConflict): replay_equivalent(tampered, tampered)
    malformed = ConfluencePageMetadata("page", "Page", "S", parent_page_id="root", ancestor_page_ids=("root",), ancestor_titles=("Root",))
    object.__setattr__(malformed, "parent_page_id", "other")
    with pytest.raises(ValueError): InventoryWindowCommit(RUN, 0, "root", 0, ConfluenceInventoryWindow((malformed,), 0, 10, 1, 1), (occurrence,), ROOTS)

def test_descendants_occurrences_cannot_be_their_own_root_but_allow_nested_root():
    roots = CanonicalIncludeRoots(("a", "b"))
    metadata = ConfluencePageMetadata("b", "B", "S", parent_page_id="a", ancestor_page_ids=("a",), ancestor_titles=("A",))
    assert InventoryOccurrence(RUN, 0, "a", 0, 0, "b", metadata, roots).page_id == "b"
    own = ConfluencePageMetadata("b", "B", "S", parent_page_id="a", ancestor_page_ids=("a",), ancestor_titles=("A",))
    with pytest.raises(ValueError): InventoryOccurrence(RUN, 1, "b", 0, 0, "b", own, roots)
    with pytest.raises(TypeError): InventoryOccurrence(RUN, 0, "a", 0, 0, "page", META, object())

def test_occurrence_requires_its_root_once_in_ancestor_path_and_revalidates_run():
    unrelated = ConfluencePageMetadata("page", "Page", "S", parent_page_id="other", ancestor_page_ids=("other",), ancestor_titles=("Other",))
    with pytest.raises(ValueError): InventoryOccurrence(RUN, 0, "root", 0, 0, "page", unrelated, ROOTS)
    repeated = ConfluencePageMetadata("page", "Page", "S", parent_page_id="root", ancestor_page_ids=("root", "root"), ancestor_titles=("Root", "Root"))
    with pytest.raises(ValueError): InventoryOccurrence(RUN, 0, "root", 0, 0, "page", repeated, ROOTS)
    tampered = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
    object.__setattr__(tampered, "value", "not-a-uuid")
    with pytest.raises(ValueError): InventoryOccurrence(tampered, 0, "root", 0, 0, "page", META, ROOTS)
    class FakeMetadata(ConfluencePageMetadata):
        pass
    with pytest.raises(TypeError): InventoryOccurrence(RUN, 0, "root", 0, 0, "page", FakeMetadata("page", "Page", "S", parent_page_id="root", ancestor_page_ids=("root",), ancestor_titles=("Root",)), ROOTS)
    class EvilString(str):
        def __eq__(self, other): return True
        def __hash__(self): return 1
    with pytest.raises(ValueError, match="invalid occurrence identity") as error:
        InventoryOccurrence(RUN, 0, EvilString("root"), 0, 0, "page", META, ROOTS)
    assert "root" not in str(error.value)
