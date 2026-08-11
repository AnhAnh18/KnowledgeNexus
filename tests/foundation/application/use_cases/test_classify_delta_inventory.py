from knowledgenexus.foundation.application.use_cases.classify_delta_inventory import ClassifyDeltaInventory
from knowledgenexus.foundation.domain.models import (
    CurrentSelectionPage,
    DeltaInventoryClassificationRequest,
    DeltaInventoryFailureCategory,
    DeltaInventoryObservation,
    DeltaInventoryScope,
    DeltaInventoryState,
    PriorConfluenceDocument,
)


def _prior(page: str, version: str = "v1") -> PriorConfluenceDocument:
    return PriorConfluenceDocument(page, f"confluence:page:{page}", version)


def _obs(page: str, status: int, version: str = "v1", **kwargs: object) -> DeltaInventoryObservation:
    return DeltaInventoryObservation(page, status, (), 0, "a" * 64, version, **kwargs)


def test_classifier_derives_present_deleted_access_and_moved() -> None:
    request = DeltaInventoryClassificationRequest(
        prior_documents=(_prior("1"), _prior("2"), _prior("3"), _prior("4")),
        current_selection=(CurrentSelectionPage("1"),),
        scope=DeltaInventoryScope(("root",)),
        observations=(_obs("2", 404), _obs("3", 403), _obs("4", 200, under_include_root=False)),
    )
    result = ClassifyDeltaInventory().execute(request)
    assert result.error_category is None
    assert [(entry.document_id, entry.state, entry.detail) for entry in result.entries] == [
        ("confluence:page:1", DeltaInventoryState.PRESENT, None),
        ("confluence:page:2", DeltaInventoryState.SOURCE_DELETED, "confluence_404_may_mask_access_revoked"),
        ("confluence:page:3", DeltaInventoryState.ACCESS_REVOKED, None),
        ("confluence:page:4", DeltaInventoryState.MOVED_OUT_OF_SCOPE, None),
    ]


def test_classifier_fails_closed_for_missing_evidence_and_in_scope_200() -> None:
    missing = DeltaInventoryClassificationRequest((_prior("1"),), (), DeltaInventoryScope(("root",)))
    assert ClassifyDeltaInventory().execute(missing).error_category is DeltaInventoryFailureCategory.INCOMPLETE_EVIDENCE
    inconsistent = DeltaInventoryClassificationRequest(
        (_prior("1"),), (), DeltaInventoryScope(("root",)), (_obs("1", 200, under_include_root=True),)
    )
    assert ClassifyDeltaInventory().execute(inconsistent).error_category is DeltaInventoryFailureCategory.INVENTORY_INCONSISTENT


def test_classifier_rejects_401_and_forged_document_id() -> None:
    request = DeltaInventoryClassificationRequest((_prior("1"),), (), DeltaInventoryScope(("root",)), (_obs("1", 401),))
    assert ClassifyDeltaInventory().execute(request).error_category is DeltaInventoryFailureCategory.INVALID_OBSERVATION
    try:
        PriorConfluenceDocument("1", "git:spen-sdk:x", "v1")
    except ValueError:
        pass
    else:
        raise AssertionError("forged document ID accepted")


def test_sensitive_models_do_not_reveal_fields_in_repr() -> None:
    assert "page_id" not in repr(_prior("secret-page"))
    assert "secret-page" not in repr(_obs("secret-page", 404))
