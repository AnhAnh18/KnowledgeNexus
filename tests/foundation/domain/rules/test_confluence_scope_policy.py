from __future__ import annotations

from knowledgenexus.foundation.domain.models import (
    ConfluenceExcludeSubtree,
    ConfluencePageMetadata,
)
from knowledgenexus.foundation.domain.rules.confluence_scope_policy import (
    ConfluenceScopePolicy,
)


def test_include_root_itself() -> None:
    assert _decide(_page(page_id="root")) == ("included", "included_root")


def test_include_normal_descendant() -> None:
    assert _decide(_page(page_id="child", ancestors=("root",))) == (
        "included",
        "included_descendant",
    )


def test_exact_page_exclusion_wins_over_ancestor_exclusion() -> None:
    decision = _decide(
        _page(page_id="skip-page", ancestors=("root", "skip-ancestor")),
        exclusions=("skip-ancestor", "skip-page"),
    )

    assert decision == ("excluded_subtree", "excluded_page:skip-page")


def test_nearest_matching_excluded_ancestor_is_selected() -> None:
    decision = _decide(
        _page(
            page_id="child",
            ancestors=("root", "excluded-far", "middle", "excluded-near"),
        ),
        exclusions=("excluded-near", "excluded-far"),
    )

    assert decision == (
        "excluded_subtree",
        "excluded_ancestor:excluded-near",
    )


def test_keywords_are_not_inputs_to_scope_policy() -> None:
    page = _page(page_id="travel-photos", ancestors=("root",))

    assert _decide(page) == ("included", "included_descendant")


def _decide(
    page: ConfluencePageMetadata,
    *,
    exclusions: tuple[str, ...] = (),
) -> tuple[str, str]:
    return ConfluenceScopePolicy.decide(
        page=page,
        include_root_ids=("root",),
        exclude_subtrees=tuple(
            ConfluenceExcludeSubtree(page_id=page_id) for page_id in exclusions
        ),
    )


def _page(
    *,
    page_id: str,
    ancestors: tuple[str, ...] = (),
) -> ConfluencePageMetadata:
    return ConfluencePageMetadata(
        page_id=page_id,
        title=page_id,
        space_key="SPACE",
        ancestor_page_ids=ancestors,
    )
