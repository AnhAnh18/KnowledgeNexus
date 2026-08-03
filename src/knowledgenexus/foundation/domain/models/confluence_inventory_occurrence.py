from __future__ import annotations
from dataclasses import dataclass
from typing import Union
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId, CanonicalIncludeRoots, _validated_roots, _validated_run_id
from knowledgenexus.foundation.domain.models.confluence_page_metadata import ConfluencePageMetadata
from knowledgenexus.foundation.domain.models.confluence_inventory_window import ConfluenceInventoryWindow

def _int(v):
    if type(v) is not int: raise TypeError("integer expected")
    if v < 0: raise ValueError("integer invalid")

def _validated_metadata(value: object) -> ConfluencePageMetadata:
    if type(value) is not ConfluencePageMetadata: raise TypeError("invalid metadata")
    if (type(value.page_id) is not str or not value.page_id or type(value.title) is not str or not value.title or type(value.space_key) is not str or not value.space_key): raise ValueError("invalid metadata")
    if any(field is not None and type(field) is not str for field in (value.parent_page_id, value.updated_at, value.source_version)): raise ValueError("invalid metadata")
    if type(value.ancestor_page_ids) is not tuple or type(value.ancestor_titles) is not tuple or type(value.labels) is not tuple: raise ValueError("invalid metadata")
    if any(type(entry) is not str for entry in value.ancestor_page_ids + value.ancestor_titles + value.labels): raise ValueError("invalid metadata")
    if value.attachment_count is not None and (type(value.attachment_count) is not int or value.attachment_count < 0): raise ValueError("invalid metadata")
    try: rebuilt = ConfluencePageMetadata(**vars(value))
    except Exception: raise ValueError("invalid metadata") from None
    if value != rebuilt: raise ValueError("invalid metadata")
    if len(rebuilt.ancestor_page_ids) != len(rebuilt.ancestor_titles): raise ValueError("invalid metadata")
    if (not rebuilt.ancestor_page_ids) != (rebuilt.parent_page_id is None): raise ValueError("invalid metadata")
    if rebuilt.ancestor_page_ids and rebuilt.parent_page_id != rebuilt.ancestor_page_ids[-1]: raise ValueError("invalid metadata")
    return rebuilt

@dataclass(frozen=True)
class InventoryOccurrence:
    run_id: CrawlRunId; include_root_ordinal: int; include_root_page_id: str; window_start: int; item_ordinal: int; page_id: str; metadata: ConfluencePageMetadata
    include_roots: CanonicalIncludeRoots
    def __post_init__(self):
        _validated_run_id(self.run_id)
        if not isinstance(self.metadata,ConfluencePageMetadata): raise TypeError("invalid occurrence")
        _validated_metadata(self.metadata)
        for x in (self.include_root_ordinal,self.window_start,self.item_ordinal): _int(x)
        if type(self.page_id) is not str or not self.page_id or self.page_id != self.metadata.page_id: raise ValueError("invalid occurrence identity")
        if type(self.include_root_page_id) is not str or not self.include_root_page_id: raise ValueError("invalid occurrence identity")
        roots = _validated_roots(self.include_roots)
        if self.page_id == self.include_root_page_id: raise ValueError("invalid occurrence identity")
        roots.validate(self.include_root_ordinal,self.include_root_page_id)
        if not self.metadata.ancestor_page_ids or self.metadata.ancestor_page_ids.count(self.include_root_page_id) != 1: raise ValueError("invalid occurrence identity")
        if self.metadata.ancestor_page_ids[0] != self.include_root_page_id: raise ValueError("invalid occurrence identity")

@dataclass(frozen=True)
class InventoryWindowCommit:
    run_id: CrawlRunId; include_root_ordinal: int; include_root_page_id: str; requested_start: int; window: ConfluenceInventoryWindow; occurrences: tuple[InventoryOccurrence,...]; include_roots: CanonicalIncludeRoots
    def __post_init__(self):
        _validated_run_id(self.run_id)
        if type(self.window) is not ConfluenceInventoryWindow: raise TypeError("invalid window commit")
        if type(self.include_root_page_id) is not str or not self.include_root_page_id: raise ValueError("invalid window commit")
        _int(self.requested_start)
        if self.requested_start != self.window.start: raise ValueError("requested start mismatch")
        try:
            normalized_items = []
            for item in self.window.items:
                rebuilt_item = _validated_metadata(item)
                normalized_items.append(rebuilt_item)
            canonical_window = ConfluenceInventoryWindow(
                tuple(normalized_items), self.window.start, self.window.limit,
                self.window.size, self.window.total_size,
            )
        except Exception:
            raise ValueError("invalid window commit") from None
        if self.window != canonical_window:
            raise ValueError("invalid window commit")
        try: occ=tuple(self.occurrences)
        except Exception: raise TypeError("invalid occurrences") from None
        roots = _validated_roots(self.include_roots)
        roots.validate(self.include_root_ordinal,self.include_root_page_id)
        if len(occ)!=self.window.size: raise ValueError("occurrence count mismatch")
        for n,o in enumerate(occ):
            if type(o) is not InventoryOccurrence: raise ValueError("invalid occurrence")
            rebuilt_metadata = _validated_metadata(o.metadata)
            try:
                rebuilt_occurrence = InventoryOccurrence(o.run_id, o.include_root_ordinal, o.include_root_page_id, o.window_start, o.item_ordinal, o.page_id, rebuilt_metadata, o.include_roots)
            except Exception:
                raise ValueError("invalid occurrence") from None
            if o != rebuilt_occurrence: raise ValueError("invalid occurrence")
            if o.run_id!=self.run_id or o.include_root_ordinal!=self.include_root_ordinal or o.include_root_page_id!=self.include_root_page_id or o.window_start!=self.window.start or o.item_ordinal!=n or o.include_roots!=self.include_roots or o.metadata!=self.window.items[n]: raise ValueError("occurrence identity mismatch")
        object.__setattr__(self,"occurrences",occ)

class InventoryReplayConflict(ValueError):
    def __init__(self, category: str): self.category=category; super().__init__(category)

def replay_equivalent(existing: InventoryWindowCommit, candidate: InventoryWindowCommit) -> bool:
    if type(existing) is not InventoryWindowCommit or type(candidate) is not InventoryWindowCommit: raise InventoryReplayConflict("inventory_identity_conflict")
    try:
        existing_rebuilt = InventoryWindowCommit(existing.run_id, existing.include_root_ordinal, existing.include_root_page_id, existing.requested_start, existing.window, existing.occurrences, existing.include_roots)
        candidate_rebuilt = InventoryWindowCommit(candidate.run_id, candidate.include_root_ordinal, candidate.include_root_page_id, candidate.requested_start, candidate.window, candidate.occurrences, candidate.include_roots)
    except Exception:
        raise InventoryReplayConflict("state_conflict") from None
    if existing != existing_rebuilt or candidate != candidate_rebuilt: raise InventoryReplayConflict("state_conflict")
    if (existing.run_id,existing.include_root_ordinal,existing.include_root_page_id,existing.requested_start)!=(candidate.run_id,candidate.include_root_ordinal,candidate.include_root_page_id,candidate.requested_start): raise InventoryReplayConflict("inventory_identity_conflict")
    if existing != candidate: raise InventoryReplayConflict("state_conflict")
    return True

inventory_window_replay_equivalent = replay_equivalent
InventoryFact = Union["InventoryRootCommit", InventoryOccurrence]
