import pytest

from knowledgenexus.foundation.domain.models import (
    CanonicalIncludeRoots, CrawlRunId, CrawlRunSnapshot, CrawlRunStatus,
    IncludeRootProgress, InventoryPhaseStatus, ResumeExplicitRunId,
    ResumeUniqueIncompleteRun, StartNewRun, CommittedCheckpointTransition,
    InventoryRootCommit, ConfluencePageMetadata,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_fingerprint import ConfluenceCrawlFingerprint

RUN = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
FINGERPRINT = ConfluenceCrawlFingerprint._from_digest("0" * 64)


def test_canonical_roots_are_sorted_unique_and_validate_member_ordinals():
    roots = CanonicalIncludeRoots(("z", "a"))
    assert roots.root_ids == ("a", "z")
    assert roots.ordinal_for("z") == 1
    roots.validate(0, "a")
    with pytest.raises(ValueError): roots.validate(0, "z")
    with pytest.raises(ValueError): CanonicalIncludeRoots(("a", "a"))
    with pytest.raises(TypeError): CanonicalIncludeRoots("root")


def test_run_id_is_canonical_uuid4_and_snapshot_generation_is_same_run():
    with pytest.raises(ValueError): CrawlRunId("123E4567-E89B-42D3-A456-426614174000")
    with pytest.raises(ValueError): CrawlRunId("123e4567-e89b-12d3-a456-426614174000")
    roots = CanonicalIncludeRoots(("root",))
    snapshot = CrawlRunSnapshot(RUN, RUN, FINGERPRINT, CrawlRunStatus.INCOMPLETE, InventoryPhaseStatus.PENDING, roots, (IncludeRootProgress.ROOT_PENDING,))
    assert snapshot.inventory_phase is InventoryPhaseStatus.PENDING
    with pytest.raises(ValueError): CrawlRunSnapshot(RUN, CrawlRunId("123e4567-e89b-42d3-a456-426614174001"), FINGERPRINT, CrawlRunStatus.INCOMPLETE, InventoryPhaseStatus.PENDING, roots, (IncludeRootProgress.ROOT_PENDING,))
    with pytest.raises(TypeError): CrawlRunSnapshot(RUN.value, RUN.value, FINGERPRINT, CrawlRunStatus.INCOMPLETE, InventoryPhaseStatus.PENDING, roots, (IncludeRootProgress.ROOT_PENDING,))
    tampered = CrawlRunId(RUN.value)
    object.__setattr__(tampered, "value", "invalid")
    with pytest.raises(ValueError): CrawlRunSnapshot(tampered, tampered, FINGERPRINT, CrawlRunStatus.INCOMPLETE, InventoryPhaseStatus.PENDING, roots, (IncludeRootProgress.ROOT_PENDING,))
    fingerprint = ConfluenceCrawlFingerprint._from_digest("1" * 64)
    object.__setattr__(fingerprint, "_value", "invalid")
    with pytest.raises(ValueError): CrawlRunSnapshot(RUN, RUN, fingerprint, CrawlRunStatus.INCOMPLETE, InventoryPhaseStatus.PENDING, roots, (IncludeRootProgress.ROOT_PENDING,))


def test_operations_are_disjoint_tags_without_fallback_selection():
    assert type(StartNewRun()) is not type(ResumeUniqueIncompleteRun())
    assert ResumeExplicitRunId(RUN).run_id == RUN
    with pytest.raises(TypeError): ResumeExplicitRunId("not-a-run")

def test_public_iterable_boundaries_sanitize_bad_iterators():
    with pytest.raises(TypeError): CanonicalIncludeRoots(None)
    class Broken:
        def __iter__(self): raise RuntimeError("private")
    with pytest.raises(TypeError): CanonicalIncludeRoots(Broken())
    roots = CanonicalIncludeRoots(("root",))
    with pytest.raises(TypeError): CrawlRunSnapshot(RUN, RUN, FINGERPRINT, CrawlRunStatus.INCOMPLETE, InventoryPhaseStatus.PENDING, roots, Broken())
    object.__setattr__(roots, "root_ids", ("root", "root"))
    with pytest.raises(ValueError): CrawlRunSnapshot(RUN, RUN, FINGERPRINT, CrawlRunStatus.INCOMPLETE, InventoryPhaseStatus.PENDING, roots, (IncludeRootProgress.ROOT_PENDING,))
    class FakeRun(CrawlRunId):
        pass
    class FakeRoots(CanonicalIncludeRoots):
        pass
    with pytest.raises(TypeError): InventoryRootCommit(FakeRun(RUN.value), 0, "root", ConfluencePageMetadata("root", "Root", "S"), roots)
    with pytest.raises(TypeError): InventoryRootCommit(RUN, 0, "root", ConfluencePageMetadata("root", "Root", "S"), FakeRoots(("root",)))

def test_root_commit_and_transitions_require_exact_root_mapping_and_metadata():
    roots = CanonicalIncludeRoots(("root",))
    root = ConfluencePageMetadata("root", "Root", "S")
    assert InventoryRootCommit(RUN, 0, "root", root, roots).metadata == root
    with pytest.raises(ValueError): InventoryRootCommit(RUN, 0, "root", ConfluencePageMetadata("other", "Root", "S"), roots)
    with pytest.raises(ValueError): InventoryRootCommit(RUN, 0, "root", ConfluencePageMetadata("root", "Root", "S", parent_page_id="p", ancestor_page_ids=("p",), ancestor_titles=("P",)), roots)
    transition = CommittedCheckpointTransition(RUN, 0, "root", IncludeRootProgress.ROOT_PENDING, IncludeRootProgress.ROOT_COMMITTED, 0, roots)
    assert transition.include_roots == roots
    object.__setattr__(root, "labels", ("z", "a", "z"))
    with pytest.raises(ValueError): InventoryRootCommit(RUN, 0, "root", root, roots)
    class FakeMetadata(ConfluencePageMetadata):
        pass
    with pytest.raises(TypeError): InventoryRootCommit(RUN, 0, "root", FakeMetadata("root", "Root", "S"), roots)
    class EvilString(str):
        def __eq__(self, other): return True
        def __hash__(self): return 1
    evil = ConfluencePageMetadata("root", "Root", "S")
    object.__setattr__(evil, "title", EvilString("secret"))
    with pytest.raises(ValueError, match="invalid root metadata") as error:
        InventoryRootCommit(RUN, 0, "root", evil, roots)
    assert "secret" not in str(error.value)

def test_snapshot_validates_root_cardinality_and_transition_consistency():
    roots = CanonicalIncludeRoots(("root",))
    transition = CommittedCheckpointTransition(RUN, 0, "root", IncludeRootProgress.ROOT_PENDING, IncludeRootProgress.ROOT_COMMITTED, 0, roots)
    snapshot = CrawlRunSnapshot(RUN, RUN, FINGERPRINT, CrawlRunStatus.INCOMPLETE, InventoryPhaseStatus.PENDING, roots, (IncludeRootProgress.ROOT_COMMITTED,), (transition,))
    assert snapshot.transitions == (transition,)
    with pytest.raises(ValueError): CrawlRunSnapshot(RUN, RUN, FINGERPRINT, CrawlRunStatus.INCOMPLETE, InventoryPhaseStatus.PENDING, roots, ())
    with pytest.raises(ValueError): CrawlRunSnapshot(RUN, RUN, FINGERPRINT, CrawlRunStatus.COMPLETE, InventoryPhaseStatus.COMPLETE, roots, (IncludeRootProgress.ROOT_PENDING,))
    with pytest.raises(ValueError): CrawlRunSnapshot(RUN, RUN, FINGERPRINT, CrawlRunStatus.INCOMPLETE, InventoryPhaseStatus.PENDING, roots, (IncludeRootProgress.DESCENDANTS_COMPLETE,))
    with pytest.raises(TypeError): CommittedCheckpointTransition(RUN, 0, "root", "root_pending", IncludeRootProgress.ROOT_COMMITTED, 0, roots)
    object.__setattr__(transition, "include_root_page_id", "tampered")
    with pytest.raises(ValueError): CrawlRunSnapshot(RUN, RUN, FINGERPRINT, CrawlRunStatus.INCOMPLETE, InventoryPhaseStatus.PENDING, roots, (IncludeRootProgress.ROOT_COMMITTED,), (transition,))
    invalid_ordinal = CommittedCheckpointTransition(RUN, 0, "root", IncludeRootProgress.ROOT_PENDING, IncludeRootProgress.ROOT_COMMITTED, 0, roots)
    object.__setattr__(invalid_ordinal, "include_root_ordinal", -1)
    with pytest.raises(ValueError): CrawlRunSnapshot(RUN, RUN, FINGERPRINT, CrawlRunStatus.INCOMPLETE, InventoryPhaseStatus.PENDING, roots, (IncludeRootProgress.ROOT_COMMITTED,), (invalid_ordinal,))
    first = CommittedCheckpointTransition(RUN, 0, "root", IncludeRootProgress.ROOT_PENDING, IncludeRootProgress.ROOT_COMMITTED, 1, roots)
    with pytest.raises(ValueError): CrawlRunSnapshot(RUN, RUN, FINGERPRINT, CrawlRunStatus.INCOMPLETE, InventoryPhaseStatus.PENDING, roots, (IncludeRootProgress.ROOT_COMMITTED,), (first, first))
