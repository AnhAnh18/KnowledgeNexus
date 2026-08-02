from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from knowledgenexus.foundation.domain.models.confluence_crawl_run import (
    InventoryRootCommit,
    _validated_roots,
    _validated_run_id,
)
from knowledgenexus.foundation.domain.models.confluence_inventory_item import (
    ConfluenceInventoryItem,
)
from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import (
    InventoryOccurrence,
)
from knowledgenexus.foundation.domain.models.confluence_page_metadata import (
    ConfluencePageMetadata,
)
from knowledgenexus.foundation.domain.rules.confluence_scope_policy import (
    ConfluenceScopePolicy,
)


class OccurrenceResolutionConflict(ValueError):
    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


def _validate_fact(
    occurrence: object,
) -> tuple[ConfluencePageMetadata, InventoryRootCommit | InventoryOccurrence]:
    if type(occurrence) is InventoryRootCommit:
        try:
            run_id = _validated_run_id(occurrence.run_id)
            roots = _validated_roots(occurrence.include_roots)
            rebuilt = InventoryRootCommit(
                run_id,
                occurrence.include_root_ordinal,
                occurrence.include_root_page_id,
                occurrence.metadata,
                roots,
            )
        except Exception:
            raise OccurrenceResolutionConflict("inventory_identity_conflict") from None
        if occurrence != rebuilt:
            raise OccurrenceResolutionConflict("inventory_identity_conflict")
        return occurrence.metadata, occurrence

    if type(occurrence) is not InventoryOccurrence:
        raise OccurrenceResolutionConflict("inventory_identity_conflict")
    try:
        run_id = _validated_run_id(occurrence.run_id)
        roots = _validated_roots(occurrence.include_roots)
        raw_metadata = occurrence.metadata
        metadata = ConfluencePageMetadata(**vars(raw_metadata))
        if raw_metadata != metadata:
            raise ValueError("non-canonical metadata")
        rebuilt = InventoryOccurrence(
            run_id,
            occurrence.include_root_ordinal,
            occurrence.include_root_page_id,
            occurrence.window_start,
            occurrence.item_ordinal,
            occurrence.page_id,
            metadata,
            roots,
        )
    except Exception:
        raise OccurrenceResolutionConflict("inventory_identity_conflict") from None
    if occurrence != rebuilt:
        raise OccurrenceResolutionConflict("inventory_identity_conflict")
    if len(metadata.ancestor_page_ids) != len(metadata.ancestor_titles):
        raise OccurrenceResolutionConflict("inventory_identity_conflict")
    if (not metadata.ancestor_page_ids) != (metadata.parent_page_id is None):
        raise OccurrenceResolutionConflict("inventory_identity_conflict")
    if metadata.ancestor_page_ids and metadata.parent_page_id != metadata.ancestor_page_ids[-1]:
        raise OccurrenceResolutionConflict("inventory_identity_conflict")
    return metadata, occurrence


def _path(metadata: ConfluencePageMetadata) -> tuple[tuple[str, str], ...]:
    return tuple(zip(metadata.ancestor_page_ids, metadata.ancestor_titles))


def _paths_compatible(
    left: tuple[tuple[str, str], ...], right: tuple[tuple[str, str], ...]
) -> bool:
    if len(left) <= len(right):
        return not left or left == right[-len(left) :]
    return not right or right == left[-len(right) :]


def resolve_inventory_occurrences(
    occurrences: Iterable[InventoryRootCommit | InventoryOccurrence],
    *,
    source_id: str = "confluence",
    include_root_ids: Iterable[str] = (),
    exclude_subtrees: Iterable = (),
) -> tuple[ConfluenceInventoryItem, ...]:
    try:
        roots = tuple(include_root_ids)
        excluded = tuple(exclude_subtrees)
        occurrence_values = tuple(occurrences)
    except Exception:
        raise OccurrenceResolutionConflict("inventory_identity_conflict") from None
    if type(source_id) is not str or not source_id:
        raise OccurrenceResolutionConflict("inventory_identity_conflict")
    if any(type(root) is not str or not root for root in roots) or len(roots) != len(set(roots)):
        raise OccurrenceResolutionConflict("inventory_identity_conflict")

    grouped: dict[str, list[ConfluencePageMetadata]] = {}
    run_ids = []
    configurations = []
    try:
        for occurrence in occurrence_values:
            metadata, fact = _validate_fact(occurrence)
            grouped.setdefault(metadata.page_id, []).append(metadata)
            run_ids.append(fact.run_id)
            configurations.append(fact.include_roots)
    except OccurrenceResolutionConflict:
        raise
    except Exception:
        raise OccurrenceResolutionConflict("inventory_identity_conflict") from None

    if configurations:
        if any(run_id != run_ids[0] for run_id in run_ids):
            raise OccurrenceResolutionConflict("inventory_identity_conflict")
        authoritative = configurations[0]
        if any(configuration != authoritative for configuration in configurations):
            raise OccurrenceResolutionConflict("inventory_identity_conflict")
        if roots and tuple(sorted(roots)) != authoritative.root_ids:
            raise OccurrenceResolutionConflict("inventory_identity_conflict")
        roots = authoritative.root_ids

    resolved: list[ConfluenceInventoryItem] = []
    for page_id, metadata_values in grouped.items():
        base = metadata_values[0]
        stable_fields = (
            "page_id",
            "title",
            "space_key",
            "updated_at",
            "source_version",
            "labels",
            "attachment_count",
        )
        paths = [_path(metadata) for metadata in metadata_values]
        for metadata, path in zip(metadata_values[1:], paths[1:]):
            if any(getattr(metadata, field) != getattr(base, field) for field in stable_fields):
                raise OccurrenceResolutionConflict("inventory_metadata_conflict")
        for index, left in enumerate(paths):
            if any(not _paths_compatible(left, right) for right in paths[index + 1 :]):
                raise OccurrenceResolutionConflict("inventory_identity_conflict")
        longest_length = max(map(len, paths))
        longest_paths = [path for path in paths if len(path) == longest_length]
        if any(path != longest_paths[0] for path in longest_paths[1:]):
            raise OccurrenceResolutionConflict("inventory_identity_conflict")
        selected_index = paths.index(longest_paths[0])
        selected = metadata_values[selected_index]
        canonical_parent = longest_paths[0][-1][0] if longest_paths[0] else None
        canonical = replace(selected, parent_page_id=canonical_parent)
        try:
            status, reason = ConfluenceScopePolicy.decide(
                page=canonical,
                include_root_ids=roots,
                exclude_subtrees=excluded,
            )
            resolved.append(
                ConfluenceInventoryItem.from_metadata(
                    source_id=source_id,
                    metadata=canonical,
                    scope_status=status,
                    scope_reason=reason,
                )
            )
        except Exception:
            raise OccurrenceResolutionConflict("inventory_identity_conflict") from None

    return tuple(sorted(resolved, key=lambda item: (item.space_key, item.ancestor_page_ids, item.page_id)))


resolve = resolve_inventory_occurrences
