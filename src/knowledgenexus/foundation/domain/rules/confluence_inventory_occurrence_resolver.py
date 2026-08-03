from __future__ import annotations
from dataclasses import replace
from collections.abc import Iterable
from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import InventoryOccurrence
from knowledgenexus.foundation.domain.models.confluence_crawl_run import InventoryRootCommit, _validated_roots, _validated_run_id
from knowledgenexus.foundation.domain.models.confluence_inventory_item import ConfluenceInventoryItem
from knowledgenexus.foundation.domain.models.confluence_page_metadata import ConfluencePageMetadata
from knowledgenexus.foundation.domain.rules.confluence_scope_policy import ConfluenceScopePolicy

class OccurrenceResolutionConflict(ValueError):
    def __init__(self, category: str): self.category=category; super().__init__(category)

def _validate(occ: object) -> tuple[ConfluencePageMetadata, object]:
    if type(occ) is InventoryRootCommit:
        try:
            rebuilt = InventoryRootCommit(occ.run_id, occ.include_root_ordinal, occ.include_root_page_id, occ.metadata, occ.include_roots)
        except Exception: raise OccurrenceResolutionConflict("inventory_identity_conflict") from None
        if occ != rebuilt: raise OccurrenceResolutionConflict("inventory_identity_conflict")
        return occ.metadata, occ
    if type(occ) is not InventoryOccurrence: raise OccurrenceResolutionConflict("inventory_identity_conflict")
    try:
        # Reconstruct both facts: frozen dataclasses can still be tampered with.
        raw_metadata = occ.metadata
        metadata = ConfluencePageMetadata(**vars(raw_metadata))
        if raw_metadata != metadata:
            raise ValueError("non-canonical metadata")
        InventoryOccurrence(occ.run_id, occ.include_root_ordinal, occ.include_root_page_id, occ.window_start, occ.item_ordinal, occ.page_id, metadata, occ.include_roots)
    except Exception:
        raise OccurrenceResolutionConflict("inventory_identity_conflict") from None
    if len(metadata.ancestor_page_ids)!=len(metadata.ancestor_titles): raise OccurrenceResolutionConflict("inventory_identity_conflict")
    if (not metadata.ancestor_page_ids) != (metadata.parent_page_id is None): raise OccurrenceResolutionConflict("inventory_identity_conflict")
    if metadata.ancestor_page_ids and metadata.parent_page_id != metadata.ancestor_page_ids[-1]: raise OccurrenceResolutionConflict("inventory_identity_conflict")
    return metadata, occ

def resolve_inventory_occurrences(occurrences: Iterable[InventoryRootCommit | InventoryOccurrence], *, source_id: str = "confluence", include_root_ids: Iterable[str] = (), exclude_subtrees: Iterable = ()) -> tuple[ConfluenceInventoryItem,...]:
    grouped = {}
    try:
        roots, excluded = tuple(include_root_ids), tuple(exclude_subtrees)
    except Exception:
        raise OccurrenceResolutionConflict("inventory_identity_conflict") from None
    if type(source_id) is not str or not source_id:
        raise OccurrenceResolutionConflict("inventory_identity_conflict")
    if any(type(root) is not str or not root for root in roots) or len(roots) != len(set(roots)):
        raise OccurrenceResolutionConflict("inventory_identity_conflict")
    try:
        occurrence_values = tuple(occurrences)
    except Exception:
        raise OccurrenceResolutionConflict("inventory_identity_conflict") from None
    canonical_configs = []
    run_ids = []
    try:
        for occ in occurrence_values:
            metadata, fact = _validate(occ); grouped.setdefault(metadata.page_id,[]).append(metadata)
            canonical_configs.append(fact.include_roots.root_ids)
            run_ids.append(fact.run_id)
    except OccurrenceResolutionConflict:
        raise
    except Exception:
        raise OccurrenceResolutionConflict("inventory_identity_conflict") from None
    if canonical_configs:
        if any(run_id != run_ids[0] for run_id in run_ids): raise OccurrenceResolutionConflict("inventory_identity_conflict")
        authoritative = canonical_configs[0]
        if any(config != authoritative for config in canonical_configs): raise OccurrenceResolutionConflict("inventory_identity_conflict")
        if roots and tuple(sorted(roots)) != authoritative: raise OccurrenceResolutionConflict("inventory_identity_conflict")
        roots = authoritative
    out=[]
    for pid, metas in grouped.items():
        base=metas[0]
        stable=("page_id","title","space_key","updated_at","source_version","labels","attachment_count")
        for m in metas[1:]:
            if any(getattr(m,k)!=getattr(base,k) for k in stable): raise OccurrenceResolutionConflict("inventory_metadata_conflict")
            a=list(zip(base.ancestor_page_ids,base.ancestor_titles)); b=list(zip(m.ancestor_page_ids,m.ancestor_titles))
            if not (not a or not b or (len(a)<=len(b) and a==b[-len(a):]) or (len(b)<=len(a) and b==a[-len(b):])): raise OccurrenceResolutionConflict("inventory_identity_conflict")
        paths=[list(zip(m.ancestor_page_ids,m.ancestor_titles)) for m in metas]; maxlen=max(map(len,paths))
        winners=[p for p in paths if len(p)==maxlen]
        if any(p!=winners[0] for p in winners[1:]): raise OccurrenceResolutionConflict("inventory_identity_conflict")
        chosen=next(m for m in metas if len(m.ancestor_page_ids)==maxlen)
        parent=chosen.ancestor_page_ids[-1] if chosen.ancestor_page_ids else None
        canonical=replace(chosen,parent_page_id=parent)
        try:
            status, reason=ConfluenceScopePolicy.decide(page=canonical,include_root_ids=roots,exclude_subtrees=excluded)
        except Exception:
            raise OccurrenceResolutionConflict("inventory_identity_conflict") from None
        try:
            out.append(ConfluenceInventoryItem.from_metadata(source_id=source_id,metadata=canonical,scope_status=status,scope_reason=reason))
        except Exception:
            raise OccurrenceResolutionConflict("inventory_identity_conflict") from None
    return tuple(sorted(out,key=lambda i:(i.space_key,i.ancestor_page_ids,i.page_id)))

resolve = resolve_inventory_occurrences
