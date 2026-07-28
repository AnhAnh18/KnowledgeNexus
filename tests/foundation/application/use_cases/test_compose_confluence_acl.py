"""Composition-boundary tests for ``ComposeConfluenceAcl`` (M6G-B).

Stage-level edge cases (zero chunks, zero Jira relations, chunk splitting,
restriction-observation shape validation, ACL policy decisions) are already
covered by their own dedicated suites (``test_build_confluence_chunks.py``,
``test_build_confluence_jira_relations.py``, ``test_materialize_confluence_acl.py``,
``test_acl_restriction_observations.py``). This file focuses on what is new in
M6G-B: the composition wiring itself, exact exception-category propagation,
restriction-ancestry binding, cross-binding/immutability invariants, ownership
isolation, and deterministic repeat.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy

import pytest

from knowledgenexus.foundation.application.use_cases.compose_confluence_acl import (
    ComposeConfluenceAcl,
    _FixedRawPageReader,
)
from knowledgenexus.foundation.application.use_cases.normalize_confluence_page import (
    CATEGORY_INVALID_PAGE_ID,
    CATEGORY_STORAGE_XHTML,
    ConfluencePageNormalizationError,
)
from knowledgenexus.foundation.domain.models import (
    AclMaterializationError,
    AclMaterializationFailureCategory,
    CharacterSpan,
    ChunkingProfile,
    ConfluenceAclCompositionAcceptanceError,
    ConfluenceAclCompositionResult,
    ConfluenceAclMaterializationResult,
    ConfluenceAclRestrictionAncestryError,
    ConfluenceChunkingError,
    ConfluenceChunkingFailureCategory,
    ConfluenceJiraRelationResult,
    JIRA_EXTRACTION_MODE,
    JIRA_KEY_PATTERN,
    JiraRelationProfile,
    TokenizationResult,
    TokenizerAsset,
)
from knowledgenexus.foundation.infrastructure.processors import (
    ConfluenceDataCenterRawPageMapper,
    ConfluenceStorageXhtmlNormalizer,
)
from knowledgenexus.foundation.ports.raw_page_observation_store_port import (
    RawPageReadError,
)
from knowledgenexus.foundation.ports.tokenizer_port import (
    TokenizerError,
    TokenizerFailureCategory,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)

PAGE_ID = "1000"
CRAWLED_AT = "2026-07-24T00:00:00Z"
RELATION_CREATED_AT = "2026-07-24T00:00:01Z"
ACL_EXTRACTED_AT = "2026-07-24T00:00:02Z"
CRAWLER_IDENTITY = "kn-foundation/1.0 (offline)"


class _WordTokenizer:
    def tokenize(self, *, text: str) -> TokenizationResult:
        return TokenizationResult(
            spans=tuple(
                CharacterSpan(match.start(), match.end())
                for match in re.finditer(r"\S+", text)
            )
        )


class _FailingTokenizer:
    def tokenize(self, *, text: str) -> TokenizationResult:
        raise TokenizerError(TokenizerFailureCategory.TOKENIZATION_FAILED)


def _chunking_profile() -> ChunkingProfile:
    return ChunkingProfile(
        chunker_version="1.2.0",
        profile_status="provisional_until_benchmark",
        active_profile="medium",
        model_name="BAAI/bge-m3",
        tokenizer_name="BAAI/bge-m3",
        tokenizer_family="SentencePiece / XLM-R",
        vector_dimension=1024,
        maximum_model_tokens=8192,
        target_tokens=450,
        minimum_tokens=5,
        hard_maximum_tokens=1000,
        overlap_tokens=64,
        code_window_target_tokens=450,
        code_window_max_lines=40,
        code_window_overlap_lines=4,
        tokenizer_repository="https://huggingface.co/BAAI/bge-m3",
        tokenizer_revision="5617a9f61b028005a4858fdac845db406aefb181",
        observed_license="MIT",
        provenance_url=(
            "https://huggingface.co/BAAI/bge-m3/tree/"
            "5617a9f61b028005a4858fdac845db406aefb181"
        ),
        tokenizer_assets=(
            TokenizerAsset(
                filename="tokenizer.json",
                byte_size=17098108,
                sha256=(
                    "21106b6d7dab2952c1d496fb21d5dc9d"
                    "b75c28ed361a05f5020bbba27810dd08"
                ),
            ),
        ),
        transformers_version="4.57.6",
        tokenizers_version="0.22.2",
        sentencepiece_version="0.2.2",
    )


def _jira_profile() -> JiraRelationProfile:
    return JiraRelationProfile(
        schema_version=1,
        extraction_mode=JIRA_EXTRACTION_MODE,
        key_pattern=JIRA_KEY_PATTERN,
        allowed_project_keys=("SVMCSPEN",),
    )


def _raw_page(
    *,
    page_id: str = PAGE_ID,
    ancestors: tuple[str, ...] = ("800", "900"),
    xhtml: str = "<h2>Overview</h2><p>Body mentions SVMCSPEN-12 once.</p>",
) -> bytes:
    payload: dict[str, object] = {
        "id": page_id,
        "type": "page",
        "title": "Fixture Foundation",
        "ancestors": [{"id": ancestor} for ancestor in ancestors],
        "space": {"key": "SPACE"},
        "version": {"number": 9, "when": "2026-07-20T01:02:03Z"},
        "body": {"storage": {"value": xhtml, "representation": "storage"}},
    }
    return json.dumps(payload).encode("utf-8")


def _observations(ids: tuple[str, ...]) -> list[dict[str, object]]:
    return [
        {
            "source_page_id": page_id,
            "http_status": 200,
            "classification": "unrestricted",
            "users": [],
            "groups": [],
        }
        for page_id in ids
    ]


def _composer(*, tokenizer: object | None = None) -> ComposeConfluenceAcl:
    return ComposeConfluenceAcl(
        chunking_profile=_chunking_profile(),
        jira_relation_profile=_jira_profile(),
        tokenizer=tokenizer or _WordTokenizer(),
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
        schema_validator=FoundationSchemaValidator(),
    )


def _execute(
    composer: ComposeConfluenceAcl,
    *,
    page_id: str = PAGE_ID,
    raw_page_bytes: bytes | None = None,
    restriction_observations: object | None = None,
    crawler_identity: str = CRAWLER_IDENTITY,
) -> ConfluenceAclCompositionResult:
    return composer.execute(
        page_id=page_id,
        raw_page_bytes=raw_page_bytes if raw_page_bytes is not None else _raw_page(),
        restriction_observations=(
            restriction_observations
            if restriction_observations is not None
            else _observations(("800", "900", PAGE_ID))
        ),
        crawled_at=CRAWLED_AT,
        relation_created_at=RELATION_CREATED_AT,
        crawler_identity=crawler_identity,
        acl_extracted_at=ACL_EXTRACTED_AT,
    )


# --- success / determinism -----------------------------------------------


def test_success_builds_full_composition_result() -> None:
    result = _execute(_composer())

    assert isinstance(result, ConfluenceAclCompositionResult)
    assert isinstance(result.jira_relation_result, ConfluenceJiraRelationResult)
    assert isinstance(
        result.acl_materialization_result, ConfluenceAclMaterializationResult
    )
    assert result.acl_materialization_result.enriched_canonical_document[
        "jira_keys"
    ] == ["SVMCSPEN-12"]
    assert tuple(
        item["source_page_id"] for item in result.validated_restriction_observations
    ) == ("800", "900", PAGE_ID)
    # Jira/ACL quality-and-metrics carry-forward is exact (Deliverable 0).
    assert (
        result.acl_materialization_result.jira_quality_observation
        == result.jira_relation_result.quality_observation
    )
    assert (
        result.acl_materialization_result.jira_metrics
        == result.jira_relation_result.metrics
    )


def test_deterministic_repeat_including_validated_observations() -> None:
    composer = _composer()
    raw_bytes = _raw_page()
    observations = _observations(("800", "900", PAGE_ID))

    first = _execute(composer, raw_page_bytes=raw_bytes, restriction_observations=observations)
    second = _execute(composer, raw_page_bytes=raw_bytes, restriction_observations=observations)

    assert first == second
    assert (
        first.validated_restriction_observations
        == second.validated_restriction_observations
    )


# --- restriction ancestry ---------------------------------------------------


@pytest.mark.parametrize(
    "ids",
    [
        ("900", PAGE_ID),
        ("700", "800", "900", PAGE_ID),
        ("900", "800", PAGE_ID),
        ("800", PAGE_ID, "900"),
        ("800", "900", "1001"),
        ("800", "900", PAGE_ID, PAGE_ID),
    ],
)
def test_missing_extra_reordered_duplicated_or_wrong_page_ancestry_fails(
    ids: tuple[str, ...],
) -> None:
    with pytest.raises(ConfluenceAclRestrictionAncestryError):
        _execute(_composer(), restriction_observations=_observations(ids))


def test_ancestry_binding_matches_raw_ancestors_exactly() -> None:
    result = _execute(
        _composer(),
        raw_page_bytes=_raw_page(ancestors=("700", "800", "900")),
        restriction_observations=_observations(("700", "800", "900", PAGE_ID)),
    )
    assert tuple(
        item["source_page_id"] for item in result.validated_restriction_observations
    ) == ("700", "800", "900", PAGE_ID)


# --- exact exception-category propagation -----------------------------------


def test_normalization_stage_failure_propagates_exact_category() -> None:
    with pytest.raises(ConfluencePageNormalizationError) as caught:
        _execute(_composer(), raw_page_bytes=_raw_page(xhtml="<p>unclosed"))
    assert caught.value.category == CATEGORY_STORAGE_XHTML


def test_chunking_stage_failure_from_a_failing_tokenizer_propagates_unchanged() -> None:
    # BuildConfluenceChunks itself wraps a raw TokenizerError into its own
    # ConfluenceChunkingError(chunking_failed); ComposeConfluenceAcl must not
    # additionally re-wrap or swallow that already-sanitized stage failure.
    with pytest.raises(ConfluenceChunkingError) as caught:
        _execute(_composer(tokenizer=_FailingTokenizer()))
    assert caught.value.category == ConfluenceChunkingFailureCategory.CHUNKING_FAILED


def test_acl_materialization_error_preserves_exact_category() -> None:
    with pytest.raises(AclMaterializationError) as caught:
        _execute(_composer(), crawler_identity="")
    assert (
        caught.value.category
        == AclMaterializationFailureCategory.INVALID_CRAWLER_IDENTITY
    )


def test_invalid_page_id_yields_normalization_category_not_raw_valueerror() -> None:
    with pytest.raises(ConfluencePageNormalizationError) as caught:
        _execute(_composer(), page_id="not-numeric")
    assert caught.value.category == CATEGORY_INVALID_PAGE_ID


# --- ownership isolation -----------------------------------------------------


def test_restriction_observations_not_mutated_or_aliased() -> None:
    observations = _observations(("800", "900", PAGE_ID))
    before = deepcopy(observations)

    result = _execute(_composer(), restriction_observations=observations)

    assert observations == before
    assert result.validated_restriction_observations is not observations
    assert all(
        entry is not source
        for entry, source in zip(
            result.validated_restriction_observations, observations, strict=True
        )
    )


def test_two_executes_validate_independently_copied_observations() -> None:
    composer = _composer()
    observations = _observations(("800", "900", PAGE_ID))

    first = _execute(composer, restriction_observations=observations)
    second = _execute(composer, restriction_observations=observations)

    assert first.validated_restriction_observations == (
        second.validated_restriction_observations
    )
    assert (
        first.validated_restriction_observations
        is not second.validated_restriction_observations
    )


# --- cross-binding / acceptance invariant (unit-level) ----------------------


def test_cross_binding_mismatch_raises_acceptance_error() -> None:
    result = _execute(_composer())
    mismatched_jira_result = ConfluenceJiraRelationResult(
        enriched_canonical_document={
            **result.jira_relation_result.enriched_canonical_document,
            "title": "Different Title",
        },
        enriched_chunks=result.jira_relation_result.enriched_chunks,
        relations=result.jira_relation_result.relations,
        quality_observation=result.jira_relation_result.quality_observation,
        metrics=result.jira_relation_result.metrics,
    )

    with pytest.raises(ConfluenceAclCompositionAcceptanceError):
        ComposeConfluenceAcl._verify_cross_binding(
            jira_relation_result=mismatched_jira_result,
            acl_result=result.acl_materialization_result,
        )


def test_cross_binding_agrees_for_a_real_composed_result() -> None:
    result = _execute(_composer())
    # No exception means the invariant holds for a genuinely composed pair.
    ComposeConfluenceAcl._verify_cross_binding(
        jira_relation_result=result.jira_relation_result,
        acl_result=result.acl_materialization_result,
    )


# --- sanitized errors / repr -------------------------------------------------


def test_restriction_ancestry_error_str_is_stable_category() -> None:
    assert str(ConfluenceAclRestrictionAncestryError()) == "restriction_ancestry"


def test_acceptance_error_str_is_stable_category() -> None:
    assert str(ConfluenceAclCompositionAcceptanceError()) == "acceptance"


def test_composition_result_repr_hides_contents() -> None:
    result = _execute(_composer())
    rendered = repr(result)
    assert "Fixture Foundation" not in rendered
    assert "SVMCSPEN-12" not in rendered
    assert PAGE_ID not in rendered


# --- fixed raw page reader (moved from the CLI test file) -------------------


def test_fixed_raw_reader_returns_only_bound_snapshot() -> None:
    reader = _FixedRawPageReader(
        expected_page_id=PAGE_ID,
        raw_bytes=b"SENSITIVE-RAW",
    )

    assert reader.read_page(page_id=PAGE_ID) == b"SENSITIVE-RAW"
    with pytest.raises(RawPageReadError):
        reader.read_page(page_id="1001")
    assert PAGE_ID not in repr(reader)
    assert "SENSITIVE" not in repr(reader)
