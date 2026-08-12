"""Pure, evidence-bound second-sync disposition classification."""

from __future__ import annotations

from knowledgenexus.foundation.domain.models.delta_inventory import (
    _DETAIL_404,
    CurrentSelectionPage,
    DeltaInventoryClassificationRequest,
    DeltaInventoryClassificationResult,
    DeltaInventoryFailureCategory,
    DeltaInventoryMetrics,
    DeltaInventoryObservation,
    DeltaInventoryStatus,
    DeltaInventoryScope,
    PriorConfluenceDocument,
)
from knowledgenexus.foundation.domain.models.delta_propagation import DeltaInventoryEntry, DeltaInventoryState


class ClassifyDeltaInventory:
    """Derive dispositions from complete selection, scope facts, and raw probes."""

    def execute(self, request: object) -> DeltaInventoryClassificationResult:
        try:
            if type(request) is not DeltaInventoryClassificationRequest:
                return self._failure(DeltaInventoryFailureCategory.INVALID_INPUT)
            try:
                if type(request.prior_documents) is not tuple:
                    raise ValueError
                for item in request.prior_documents:
                    PriorConfluenceDocument.__post_init__(item)
                if len({item.page_id for item in request.prior_documents}) != len(request.prior_documents):
                    raise ValueError
            except Exception:
                return self._failure(DeltaInventoryFailureCategory.INVALID_PRIOR_SNAPSHOT)
            try:
                if type(request.current_selection) is not tuple:
                    raise ValueError
                DeltaInventoryScope.__post_init__(request.scope)
                for item in request.current_selection:
                    CurrentSelectionPage.__post_init__(item)
                if len({item.page_id for item in request.current_selection}) != len(request.current_selection):
                    raise ValueError
            except Exception:
                return self._failure(DeltaInventoryFailureCategory.INVALID_SELECTION_SCOPE)
            try:
                if type(request.observations) is not tuple:
                    raise ValueError
                for item in request.observations:
                    DeltaInventoryObservation.__post_init__(item)
                if len({item.page_id for item in request.observations}) != len(request.observations):
                    raise ValueError
            except Exception:
                return self._failure(DeltaInventoryFailureCategory.INVALID_OBSERVATION)
            prior = {item.page_id: item for item in request.prior_documents}
            selected = {item.page_id for item in request.current_selection}
            observations = {item.page_id: item for item in request.observations}
            entries: list[DeltaInventoryEntry] = []

            for page_id in sorted(selected):
                entries.append(DeltaInventoryEntry(_document_id(page_id), DeltaInventoryState.PRESENT))

            for page_id in sorted(set(prior) - selected):
                document = prior[page_id]
                observation = observations.get(page_id)
                if observation is None:
                    return self._failure(DeltaInventoryFailureCategory.INCOMPLETE_EVIDENCE)
                if observation.source_version_last_seen != document.source_version_last_seen:
                    return self._failure(DeltaInventoryFailureCategory.INVALID_OBSERVATION)
                state, detail = self._classify_missing(observation, request.scope)
                entries.append(DeltaInventoryEntry(_document_id(page_id), state, document.source_version_last_seen, detail))

            if set(observations) - (set(prior) - selected):
                return self._failure(DeltaInventoryFailureCategory.INVALID_OBSERVATION)
            entries.sort(key=lambda entry: entry.document_id)
            metrics = DeltaInventoryMetrics(
                present_count=sum(entry.state is DeltaInventoryState.PRESENT for entry in entries),
                source_deleted_count=sum(entry.state is DeltaInventoryState.SOURCE_DELETED for entry in entries),
                access_revoked_count=sum(entry.state is DeltaInventoryState.ACCESS_REVOKED for entry in entries),
                moved_out_of_scope_count=sum(entry.state is DeltaInventoryState.MOVED_OUT_OF_SCOPE for entry in entries),
            )
            try:
                return DeltaInventoryClassificationResult(DeltaInventoryStatus.SUCCESS, tuple(entries), metrics)
            except (TypeError, ValueError):
                return self._failure(DeltaInventoryFailureCategory.INVALID_RESULT)
        except _ClassificationFailure as exc:
            return self._failure(exc.category)
        except Exception:
            return self._failure(DeltaInventoryFailureCategory.INTERNAL_FAILURE)

    @staticmethod
    def _classify_missing(observation: DeltaInventoryObservation, scope: object) -> tuple[DeltaInventoryState, str | None]:
        status = observation.http_status
        if status == 404:
            return DeltaInventoryState.SOURCE_DELETED, _DETAIL_404
        if status == 403:
            return DeltaInventoryState.ACCESS_REVOKED, None
        if status == 401:
            raise _ClassificationFailure(DeltaInventoryFailureCategory.INVALID_OBSERVATION)
        if status == 200:
            under_include_root = observation.page_id in scope.include_root_page_ids or bool(set(observation.ancestor_page_ids) & set(scope.include_root_page_ids))
            excluded_by_id = observation.page_id in scope.excluded_page_ids
            excluded_by_ancestor = bool(set(observation.ancestor_page_ids) & set(scope.excluded_ancestor_page_ids))
            if excluded_by_id or excluded_by_ancestor or not under_include_root:
                return DeltaInventoryState.MOVED_OUT_OF_SCOPE, None
            raise _ClassificationFailure(DeltaInventoryFailureCategory.INVENTORY_INCONSISTENT)
        if 400 <= status <= 499:
            raise _ClassificationFailure(DeltaInventoryFailureCategory.INVALID_OBSERVATION)
        raise _ClassificationFailure(DeltaInventoryFailureCategory.INCOMPLETE_EVIDENCE)

    @staticmethod
    def _failure(category: DeltaInventoryFailureCategory) -> DeltaInventoryClassificationResult:
        return DeltaInventoryClassificationResult(DeltaInventoryStatus.FAILED, error_category=category)


class _ClassificationFailure(Exception):
    def __init__(self, category: DeltaInventoryFailureCategory) -> None:
        self.category = category


def _document_id(page_id: str) -> str:
    from knowledgenexus.foundation.domain.rules.document_id_generator import DocumentIdGenerator

    return DocumentIdGenerator.confluence_page_id(page_id)


__all__ = ["ClassifyDeltaInventory"]
