from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.models.confluence_page_content import (
    ConfluencePageNormalizationResult,
    ConfluenceStorageNormalization,
    NormalizationReferenceIntent,
)


def _intent(**overrides: object) -> NormalizationReferenceIntent:
    values: dict[str, object] = {
        "ordinal": 1,
        "kind": "drawio",
        "status": "deferred_mvp",
        "target_identity": "flow",
        "placeholder_identity": "flow",
    }
    values.update(overrides)
    return NormalizationReferenceIntent(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"ordinal": True},
        {"ordinal": 0},
        {"kind": "other"},
        {"status": "resolved"},
        {"target_identity": "flow\nsecret"},
        {"target_identity": "bad\ud800"},
        {"target_identity": "flow", "placeholder_identity": "other"},
        {"kind": "include_page", "status": "deferred_mvp"},
        {"target_identity": "unknown", "placeholder_identity": "unknown", "status": "deferred_mvp"},
    ],
)
def test_reference_intent_rejects_invalid_runtime_values(overrides: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        _intent(**overrides)


def test_normalization_models_copy_mutable_records_and_propagate_intents() -> None:
    counters = {"handled_macros": {"drawio": 1}}
    warnings = ({"code": "x"},)
    intent = _intent()
    storage = ConfluenceStorageNormalization(
        normalized_body_text="body",
        counters=counters,
        warnings=warnings,
        reference_intents=(intent,),
    )
    counters["handled_macros"]["drawio"] = 9
    assert storage.counters == {"handled_macros": {"drawio": 1}}
    assert storage.reference_intents == (intent,)

    document = {"document_id": "doc", "metadata": {"safe": True}}
    result = ConfluencePageNormalizationResult(
        normalized_body_text=storage.normalized_body_text,
        canonical_document=document,
        counters=storage.counters,
        warnings=storage.warnings,
        reference_intents=storage.reference_intents,
    )
    document["metadata"]["safe"] = False
    assert result.canonical_document["metadata"] == {"safe": True}


@pytest.mark.parametrize("value", [None, object(), [], [1]])
def test_normalization_models_reject_malformed_intent_collections(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        ConfluenceStorageNormalization(
            normalized_body_text="body",
            counters={},
            warnings=(),
            reference_intents=value,
        )


def test_normalization_models_reject_wrong_result_shape_before_use() -> None:
    with pytest.raises(TypeError):
        ConfluenceStorageNormalization(
            normalized_body_text="body",
            counters={},
            warnings=(),
            reference_intents=(object(),),
        )


@pytest.mark.parametrize(
    "intents",
    [
        (_intent(ordinal=2),),
        (_intent(ordinal=2), _intent(ordinal=1)),
    ],
)
def test_normalization_models_reject_noncontiguous_intent_ordinals(
    intents: tuple[NormalizationReferenceIntent, ...],
) -> None:
    with pytest.raises(ValueError):
        ConfluenceStorageNormalization(
            normalized_body_text="body",
            counters={},
            warnings=(),
            reference_intents=intents,
        )
