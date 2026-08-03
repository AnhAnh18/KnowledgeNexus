from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Union
from knowledgenexus.foundation.domain.models.confluence_page_metadata import ConfluencePageMetadata
from knowledgenexus.foundation.domain.models.confluence_crawl_fingerprint import ConfluenceCrawlFingerprint

_UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

def _s(name: str, value: object) -> str:
    if type(value) is not str: raise TypeError(f"{name} invalid")
    if not value: raise ValueError(f"{name} invalid")
    return value
def _i(name: str, value: object) -> int:
    if type(value) is not int: raise TypeError(f"{name} invalid")
    if value < 0: raise ValueError(f"{name} invalid")
    return value

@dataclass(frozen=True)
class CrawlRunId:
    value: str
    def __post_init__(self):
        if type(self.value) is not str or not _UUID4.fullmatch(self.value): raise ValueError("invalid run id")
        if str(uuid.UUID(self.value)) != self.value: raise ValueError("invalid run id")
    def __str__(self): return self.value

def _validated_run_id(value: object) -> CrawlRunId:
    if type(value) is not CrawlRunId: raise TypeError("invalid run id")
    try: rebuilt = CrawlRunId(value.value)
    except Exception: raise ValueError("invalid run id") from None
    if value != rebuilt: raise ValueError("invalid run id")
    return rebuilt

def _validated_fingerprint(value: object) -> ConfluenceCrawlFingerprint:
    if type(value) is not ConfluenceCrawlFingerprint: raise TypeError("invalid crawl fingerprint")
    try: rebuilt = ConfluenceCrawlFingerprint._from_digest(value.value)
    except Exception: raise ValueError("invalid crawl fingerprint") from None
    if value != rebuilt: raise ValueError("invalid crawl fingerprint")
    return rebuilt

def _validate_metadata_primitives(value: ConfluencePageMetadata) -> None:
    if any(type(field) is not str or not field for field in (value.page_id, value.title, value.space_key)): raise ValueError("invalid root metadata")
    if any(field is not None and type(field) is not str for field in (value.parent_page_id, value.updated_at, value.source_version)): raise ValueError("invalid root metadata")
    if type(value.ancestor_page_ids) is not tuple or type(value.ancestor_titles) is not tuple or type(value.labels) is not tuple: raise ValueError("invalid root metadata")
    if any(type(entry) is not str for entry in value.ancestor_page_ids + value.ancestor_titles + value.labels): raise ValueError("invalid root metadata")
    if value.attachment_count is not None and (type(value.attachment_count) is not int or value.attachment_count < 0): raise ValueError("invalid root metadata")

@dataclass(frozen=True)
class CrawlSessionId:
    value: str
    def __post_init__(self): _s("session id", self.value)
    def __str__(self): return self.value

@dataclass(frozen=True)
class StartNewRun: pass
@dataclass(frozen=True)
class ResumeExplicitRunId:
    run_id: CrawlRunId
    def __post_init__(self):
        _validated_run_id(self.run_id)
@dataclass(frozen=True)
class ResumeUniqueIncompleteRun: pass
CrawlRunOperation = Union[StartNewRun, ResumeExplicitRunId, ResumeUniqueIncompleteRun]

@dataclass(frozen=True)
class CanonicalIncludeRoots:
    root_ids: tuple[str, ...]
    def __post_init__(self):
        if isinstance(self.root_ids, (str, bytes)): raise TypeError("invalid include roots")
        try: vals = tuple(self.root_ids)
        except Exception: raise TypeError("invalid include roots") from None
        if not vals or any(type(x) is not str or not x for x in vals) or len(set(vals)) != len(vals): raise ValueError("invalid include roots")
        object.__setattr__(self, "root_ids", tuple(sorted(vals)))
    @property
    def ordinals(self): return tuple(enumerate(self.root_ids))
    def ordinal_for(self, root_id: str) -> int:
        try: return self.root_ids.index(root_id)
        except ValueError: raise ValueError("unknown include root") from None
    def validate(self, ordinal: int, root_id: str):
        if type(ordinal) is not int or ordinal < 0 or ordinal >= len(self.root_ids) or self.root_ids[ordinal] != root_id: raise ValueError("invalid include root reference")

def _validated_roots(value: object) -> CanonicalIncludeRoots:
    if type(value) is not CanonicalIncludeRoots: raise TypeError("invalid include roots")
    try: rebuilt = CanonicalIncludeRoots(value.root_ids)
    except Exception: raise ValueError("invalid include roots") from None
    if value != rebuilt: raise ValueError("invalid include roots")
    return rebuilt

class CrawlRunStatus(str, Enum): INCOMPLETE = "incomplete"; COMPLETE = "complete"
class InventoryPhaseStatus(str, Enum): PENDING = "pending"; COMPLETE = "complete"
class IncludeRootProgress(str, Enum): ROOT_PENDING="root_pending"; ROOT_COMMITTED="root_committed"; DESCENDANTS_PENDING="descendants_pending"; DESCENDANTS_COMPLETE="descendants_complete"

@dataclass(frozen=True)
class InventoryRootCommit:
    run_id: CrawlRunId; include_root_ordinal: int; include_root_page_id: str; metadata: ConfluencePageMetadata; include_roots: CanonicalIncludeRoots
    def __post_init__(self):
        _validated_run_id(self.run_id)
        _i("ordinal", self.include_root_ordinal); _s("root id", self.include_root_page_id)
        _validated_roots(self.include_roots).validate(self.include_root_ordinal, self.include_root_page_id)
        if type(self.metadata) is not ConfluencePageMetadata: raise TypeError("invalid root metadata")
        _validate_metadata_primitives(self.metadata)
        try: rebuilt_metadata = ConfluencePageMetadata(**vars(self.metadata))
        except Exception: raise ValueError("invalid root metadata") from None
        if self.metadata != rebuilt_metadata or self.metadata.page_id != self.include_root_page_id: raise ValueError("invalid root metadata")
        if self.metadata.parent_page_id is not None or self.metadata.ancestor_page_ids or self.metadata.ancestor_titles: raise ValueError("invalid root metadata")

@dataclass(frozen=True)
class CommittedCheckpointTransition:
    run_id: CrawlRunId; include_root_ordinal: int; include_root_page_id: str; from_progress: IncludeRootProgress; to_progress: IncludeRootProgress; sequence: int; include_roots: CanonicalIncludeRoots
    def __post_init__(self):
        _validated_run_id(self.run_id)
        _i("ordinal", self.include_root_ordinal); _s("root id", self.include_root_page_id); _i("sequence", self.sequence)
        _validated_roots(self.include_roots).validate(self.include_root_ordinal, self.include_root_page_id)
        if not isinstance(self.from_progress, IncludeRootProgress) or not isinstance(self.to_progress, IncludeRootProgress): raise TypeError("invalid progress transition")
        edges = {(IncludeRootProgress.ROOT_PENDING,IncludeRootProgress.ROOT_COMMITTED),(IncludeRootProgress.ROOT_COMMITTED,IncludeRootProgress.DESCENDANTS_PENDING),(IncludeRootProgress.DESCENDANTS_PENDING,IncludeRootProgress.DESCENDANTS_PENDING),(IncludeRootProgress.DESCENDANTS_PENDING,IncludeRootProgress.DESCENDANTS_COMPLETE)}
        if (self.from_progress,self.to_progress) not in edges: raise ValueError("invalid progress transition")

@dataclass(frozen=True)
class CrawlRunSnapshot:
    run_id: CrawlRunId; generation_id: CrawlRunId; fingerprint: ConfluenceCrawlFingerprint; status: CrawlRunStatus; inventory_phase: InventoryPhaseStatus; include_roots: CanonicalIncludeRoots; root_progress: tuple[IncludeRootProgress, ...]; transitions: tuple[CommittedCheckpointTransition, ...] = ()
    def __post_init__(self):
        _validated_run_id(self.run_id); _validated_run_id(self.generation_id)
        _validated_fingerprint(self.fingerprint)
        if self.run_id != self.generation_id: raise ValueError("generation identity mismatch")
        if not isinstance(self.status, CrawlRunStatus): raise TypeError("invalid status")
        if not isinstance(self.inventory_phase, InventoryPhaseStatus): raise TypeError("invalid inventory phase")
        _validated_roots(self.include_roots)
        try: progress, transitions = tuple(self.root_progress), tuple(self.transitions)
        except Exception: raise TypeError("invalid snapshot facts") from None
        if len(progress) != len(self.include_roots.root_ids) or not all(isinstance(x, IncludeRootProgress) for x in progress): raise ValueError("invalid root progress")
        if not all(type(x) is CommittedCheckpointTransition for x in transitions): raise ValueError("invalid transitions")
        for transition in transitions:
            try:
                rebuilt = CommittedCheckpointTransition(transition.run_id, transition.include_root_ordinal, transition.include_root_page_id, transition.from_progress, transition.to_progress, transition.sequence, transition.include_roots)
            except Exception:
                raise ValueError("invalid transitions") from None
            if transition != rebuilt: raise ValueError("invalid transitions")
        sequences = [x.sequence for x in transitions]
        if any(type(sequence) is not int or sequence < 0 for sequence in sequences) or any(left >= right for left, right in zip(sequences, sequences[1:])): raise ValueError("invalid transition sequence")
        expected = [IncludeRootProgress.ROOT_PENDING] * len(progress)
        for transition in transitions:
            if transition.run_id != self.run_id or transition.include_roots != self.include_roots: raise ValueError("invalid transition identity")
            if expected[transition.include_root_ordinal] != transition.from_progress: raise ValueError("inconsistent transition")
            expected[transition.include_root_ordinal] = transition.to_progress
        if tuple(expected) != progress: raise ValueError("inconsistent root progress")
        roots_complete = all(x is IncludeRootProgress.DESCENDANTS_COMPLETE for x in progress)
        if (self.inventory_phase is InventoryPhaseStatus.COMPLETE) != roots_complete: raise ValueError("inconsistent inventory phase")
        if self.status is CrawlRunStatus.COMPLETE: raise ValueError("run completion is outside inventory snapshot")
        object.__setattr__(self,"root_progress",progress); object.__setattr__(self,"transitions",transitions)
