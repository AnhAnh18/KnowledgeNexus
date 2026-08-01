import pytest

from knowledgenexus.foundation.domain.models import CanonicalIncludeRoots, CrawlRunId, ConfluencePageMetadata, InventoryOccurrence, InventoryRootCommit
from knowledgenexus.foundation.domain.models.confluence_source_config import ConfluenceExcludeSubtree
from knowledgenexus.foundation.domain.rules.confluence_inventory_occurrence_resolver import OccurrenceResolutionConflict, resolve_inventory_occurrences

RUN = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
ROOTS = CanonicalIncludeRoots(("nested", "root"))

def _occ(meta, ordinal=1): return InventoryOccurrence(RUN, ordinal, ROOTS.root_ids[ordinal], 0, ordinal, meta.page_id, meta, ROOTS)
def _meta(path=("root",), titles=("Root",), **changes):
    values = dict(page_id="page", title="Page", space_key="S", parent_page_id=path[-1] if path else None, ancestor_page_ids=path, ancestor_titles=titles, updated_at="t", source_version="v", labels=("a",), attachment_count=1)
    values.update(changes); return ConfluencePageMetadata(**values)

def test_nested_roots_are_order_independent_and_select_longest_contextual_parent():
    short = _occ(_meta(("nested",), ("Nested",)), 0)
    long = _occ(_meta(("root", "nested"), ("Root", "Nested")), 1)
    first = resolve_inventory_occurrences((short, long), include_root_ids=ROOTS.root_ids)
    second = resolve_inventory_occurrences((long, short), include_root_ids=ROOTS.root_ids)
    assert first == second and first[0].parent_page_id == "nested"

def test_empty_path_root_and_nested_path_are_compatible_and_longest_scope_wins():
    root = InventoryRootCommit(RUN, 0, "nested", ConfluencePageMetadata("nested", "Page", "S", updated_at="t", source_version="v", labels=("a",), attachment_count=1), ROOTS)
    nested_meta = _meta(("root", "nested"), ("Root", "Nested"), page_id="nested")
    nested = _occ(nested_meta, 1)
    resolved = resolve_inventory_occurrences((root, nested), exclude_subtrees=(ConfluenceExcludeSubtree("nested"),))
    assert resolved[0].scope_status == "excluded_subtree"

@pytest.mark.parametrize("field,value", [("title","Other"),("space_key","X"),("updated_at","u"),("source_version","x"),("labels",("b",)),("attachment_count",2)])
def test_stable_metadata_conflicts_fail_sanitized(field, value):
    values={field:value}
    with pytest.raises(OccurrenceResolutionConflict, match="metadata_conflict") as error:
        resolve_inventory_occurrences((_occ(_meta()), _occ(_meta(**values))))
    assert "page" not in str(error.value)

def test_bad_singleton_path_title_alignment_and_parent_context_fail_closed():
    broken = _meta(("root",), ("Root",))
    occurrence = _occ(broken)
    object.__setattr__(broken, "ancestor_titles", ())
    with pytest.raises(OccurrenceResolutionConflict, match="inventory_identity_conflict"):
        resolve_inventory_occurrences((occurrence,))
    bad_parent = _meta(("root",), ("Root",))
    bad_occurrence = _occ(bad_parent)
    object.__setattr__(bad_parent, "parent_page_id", "other")
    with pytest.raises(OccurrenceResolutionConflict, match="inventory_identity_conflict"):
        resolve_inventory_occurrences((bad_occurrence,))

def test_path_title_conflict_and_divergent_paths_fail_and_output_uses_m5_order():
    with pytest.raises(OccurrenceResolutionConflict):
        resolve_inventory_occurrences((_occ(_meta()), _occ(_meta(("root",), ("Other",)))))
    z = _occ(_meta(page_id="z", space_key="Z")); a = _occ(_meta(page_id="a", space_key="A"))
    assert [item.page_id for item in resolve_inventory_occurrences((z,a))] == ["a", "z"]

def test_tampered_metadata_and_malformed_occurrence_iterators_are_sanitized():
    tampered = _meta()
    occurrence = _occ(tampered)
    object.__setattr__(tampered, "labels", ("z", "a", "z"))
    with pytest.raises(OccurrenceResolutionConflict, match="inventory_identity_conflict"):
        resolve_inventory_occurrences((occurrence,))
    with pytest.raises(OccurrenceResolutionConflict, match="inventory_identity_conflict"):
        resolve_inventory_occurrences(object())
    class Broken:
        def __iter__(self): raise ValueError("private details")
    with pytest.raises(OccurrenceResolutionConflict, match="inventory_identity_conflict"):
        resolve_inventory_occurrences(Broken())
    class BrokenRuntime:
        def __iter__(self): raise RuntimeError("private details")
    with pytest.raises(OccurrenceResolutionConflict, match="inventory_identity_conflict"):
        resolve_inventory_occurrences(BrokenRuntime())
    with pytest.raises(OccurrenceResolutionConflict, match="inventory_identity_conflict"):
        resolve_inventory_occurrences((_occ(_meta()),), source_id="")
    with pytest.raises(OccurrenceResolutionConflict, match="inventory_identity_conflict"):
        resolve_inventory_occurrences((_occ(_meta()),), include_root_ids=(None,))

def test_occurrence_roots_are_authoritative_and_mixed_or_mismatched_configs_fail():
    occurrence = _occ(_meta())
    assert resolve_inventory_occurrences((occurrence,))[0].page_id == "page"
    with pytest.raises(OccurrenceResolutionConflict, match="inventory_identity_conflict"):
        resolve_inventory_occurrences((occurrence,), include_root_ids=("wrong",))
    other_run = CrawlRunId("123e4567-e89b-42d3-a456-426614174001")
    mixed = InventoryOccurrence(other_run, 1, "root", 0, 1, "page", _meta(), ROOTS)
    with pytest.raises(OccurrenceResolutionConflict, match="inventory_identity_conflict"):
        resolve_inventory_occurrences((occurrence, mixed))
    with pytest.raises(OccurrenceResolutionConflict, match="inventory_identity_conflict"):
        resolve_inventory_occurrences((), include_root_ids=("root", "root"))

def test_scope_policy_runtime_error_is_sanitized(monkeypatch):
    from knowledgenexus.foundation.domain.rules.confluence_inventory_occurrence_resolver import ConfluenceScopePolicy
    monkeypatch.setattr(ConfluenceScopePolicy, "decide", staticmethod(lambda **_: (_ for _ in ()).throw(RuntimeError("private"))))
    with pytest.raises(OccurrenceResolutionConflict, match="inventory_identity_conflict"):
        resolve_inventory_occurrences((_occ(_meta()),))

def test_resolver_rejects_adversarial_string_scope_inputs():
    class EvilString(str):
        def __eq__(self, other): return True
        def __hash__(self): return 1
    with pytest.raises(OccurrenceResolutionConflict, match="inventory_identity_conflict") as error:
        resolve_inventory_occurrences((_occ(_meta()),), source_id=EvilString("secret"))
    assert "secret" not in str(error.value)

def test_resolver_rejects_tampered_nested_root_mapping():
    occurrence = _occ(_meta())
    object.__setattr__(occurrence.include_roots, "root_ids", ("nested", "nested"))
    with pytest.raises(OccurrenceResolutionConflict, match="inventory_identity_conflict"):
        resolve_inventory_occurrences((occurrence,))
