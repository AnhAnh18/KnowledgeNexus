from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.models import (
    ConfluenceExcludeSubtree,
    ConfluenceIncludeRoot,
    ConfluencePageMetadata,
    ConfluenceSourceConfig,
)


def test_valid_minimal_source_config_copies_collections_to_tuples() -> None:
    roots = [ConfluenceIncludeRoot(page_id="root-1")]
    include_keywords = ["architecture"]

    config = ConfluenceSourceConfig(
        source_id="wiki-poc",
        space_key="SPACE",
        include_roots=roots,  # type: ignore[arg-type]
        include_keywords=include_keywords,  # type: ignore[arg-type]
    )

    roots.append(ConfluenceIncludeRoot(page_id="root-2"))
    include_keywords.append("later")
    assert config.include_roots == (ConfluenceIncludeRoot(page_id="root-1"),)
    assert config.include_keywords == ("architecture",)
    assert config.page_size == 50


def test_multiple_roots_exclusions_and_keywords_are_preserved() -> None:
    config = ConfluenceSourceConfig(
        source_id="wiki-poc",
        space_key="SPACE",
        include_roots=(
            ConfluenceIncludeRoot(page_id="root-2", name="Second"),
            ConfluenceIncludeRoot(page_id="root-1", name="First"),
        ),
        exclude_subtrees=(
            ConfluenceExcludeSubtree(page_id="skip", reason="manual review"),
        ),
        include_keywords=("design",),
        exclude_keywords=("travel",),
        page_size=25,
    )

    assert config.include_roots[0].page_id == "root-2"
    assert config.exclude_subtrees[0].reason == "manual review"
    assert config.page_size == 25


@pytest.mark.parametrize(
    "field_name",
    [
        "include_roots",
        "exclude_subtrees",
        "include_keywords",
        "exclude_keywords",
    ],
)
@pytest.mark.parametrize("scalar", ["root", b"root"])
def test_config_collection_fields_reject_string_and_bytes_scalars(
    field_name: str,
    scalar: object,
) -> None:
    values = {
        "source_id": "wiki-poc",
        "space_key": "SPACE",
        "include_roots": (ConfluenceIncludeRoot(page_id="root"),),
        field_name: scalar,
    }

    with pytest.raises(TypeError, match="expects a collection"):
        ConfluenceSourceConfig(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["source_id", "space_key"])
def test_required_config_strings_must_not_be_empty(field: str) -> None:
    values = {
        "source_id": "wiki-poc",
        "space_key": "SPACE",
        "include_roots": (ConfluenceIncludeRoot(page_id="root"),),
    }
    values[field] = ""

    with pytest.raises(ValueError, match=field):
        ConfluenceSourceConfig(**values)  # type: ignore[arg-type]


def test_at_least_one_include_root_is_required() -> None:
    with pytest.raises(ValueError, match="include_roots"):
        ConfluenceSourceConfig(
            source_id="wiki-poc",
            space_key="SPACE",
            include_roots=(),
        )


def test_duplicate_include_root_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="include-root"):
        ConfluenceSourceConfig(
            source_id="wiki-poc",
            space_key="SPACE",
            include_roots=(
                ConfluenceIncludeRoot(page_id="root"),
                ConfluenceIncludeRoot(page_id="root"),
            ),
        )


def test_duplicate_exclusion_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="excluded-subtree"):
        ConfluenceSourceConfig(
            source_id="wiki-poc",
            space_key="SPACE",
            include_roots=(ConfluenceIncludeRoot(page_id="root"),),
            exclude_subtrees=(
                ConfluenceExcludeSubtree(page_id="skip"),
                ConfluenceExcludeSubtree(page_id="skip"),
            ),
        )


def test_include_exclude_overlap_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not overlap"):
        ConfluenceSourceConfig(
            source_id="wiki-poc",
            space_key="SPACE",
            include_roots=(ConfluenceIncludeRoot(page_id="same"),),
            exclude_subtrees=(ConfluenceExcludeSubtree(page_id="same"),),
        )


@pytest.mark.parametrize("page_size", [0, -1])
def test_page_size_must_be_positive(page_size: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        _config(page_size=page_size)


@pytest.mark.parametrize("page_size", [True, 1.5, "10"])
def test_page_size_must_be_an_actual_integer(page_size: object) -> None:
    with pytest.raises(TypeError, match="integer"):
        _config(page_size=page_size)  # type: ignore[arg-type]


def test_metadata_preserves_ancestor_order_and_normalizes_labels() -> None:
    ancestor_ids = ["grandparent", "parent"]
    labels = ["zeta", "alpha", "zeta"]

    metadata = ConfluencePageMetadata(
        page_id="page",
        title="Title",
        space_key="SPACE",
        ancestor_page_ids=ancestor_ids,  # type: ignore[arg-type]
        ancestor_titles=("Grandparent", "Parent"),
        labels=labels,  # type: ignore[arg-type]
    )

    ancestor_ids.reverse()
    labels.append("later")
    assert metadata.ancestor_page_ids == ("grandparent", "parent")
    assert metadata.labels == ("alpha", "zeta")


@pytest.mark.parametrize(
    "field_name",
    ["ancestor_page_ids", "ancestor_titles", "labels"],
)
@pytest.mark.parametrize("scalar", ["root", b"root"])
def test_metadata_collection_fields_reject_string_and_bytes_scalars(
    field_name: str,
    scalar: object,
) -> None:
    values = {
        "page_id": "page",
        "title": "Title",
        "space_key": "SPACE",
        field_name: scalar,
    }

    with pytest.raises(TypeError, match="collection of strings"):
        ConfluencePageMetadata(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("field_name", ["ancestor_page_ids", "ancestor_titles"])
@pytest.mark.parametrize(
    "unordered_values",
    [{"root", "parent"}, {"root": 1, "parent": 2}],
)
def test_ordered_ancestor_fields_reject_sets_and_dicts(
    field_name: str,
    unordered_values: object,
) -> None:
    values = {
        "page_id": "page",
        "title": "Title",
        "space_key": "SPACE",
        field_name: unordered_values,
    }

    with pytest.raises(TypeError, match="ordered collection of strings"):
        ConfluencePageMetadata(**values)  # type: ignore[arg-type]


def test_labels_accept_unordered_collection_and_remain_deterministic() -> None:
    metadata = ConfluencePageMetadata(
        page_id="page",
        title="Title",
        space_key="SPACE",
        labels={"zeta", "alpha", "zeta"},  # type: ignore[arg-type]
    )

    assert metadata.labels == ("alpha", "zeta")


@pytest.mark.parametrize("attachment_count", [None, 0, 7])
def test_metadata_accepts_unknown_zero_and_positive_attachment_counts(
    attachment_count: int | None,
) -> None:
    assert _metadata(attachment_count=attachment_count).attachment_count == attachment_count


@pytest.mark.parametrize("attachment_count", [-1])
def test_metadata_rejects_negative_attachment_count(attachment_count: int) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _metadata(attachment_count=attachment_count)


@pytest.mark.parametrize("attachment_count", [True, 1.5, "1"])
def test_metadata_rejects_non_integer_attachment_count(
    attachment_count: object,
) -> None:
    with pytest.raises(TypeError, match="integer or None"):
        _metadata(attachment_count=attachment_count)  # type: ignore[arg-type]


def _config(*, page_size: int) -> ConfluenceSourceConfig:
    return ConfluenceSourceConfig(
        source_id="wiki-poc",
        space_key="SPACE",
        include_roots=(ConfluenceIncludeRoot(page_id="root"),),
        page_size=page_size,
    )


def _metadata(*, attachment_count: int | None) -> ConfluencePageMetadata:
    return ConfluencePageMetadata(
        page_id="page",
        title="Title",
        space_key="SPACE",
        attachment_count=attachment_count,
    )
