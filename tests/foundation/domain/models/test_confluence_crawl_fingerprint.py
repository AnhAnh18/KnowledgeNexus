from __future__ import annotations

import math
from collections.abc import Iterator, Mapping

import pytest

from knowledgenexus.foundation.domain.models import (
    ConfluenceCrawlFingerprint,
    ConfluenceCrawlFingerprintBuilder,
    ConfluenceExcludeSubtree,
    ConfluenceIncludeRoot,
    ConfluenceSourceConfig,
    build_confluence_crawl_fingerprint,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_fingerprint import (
    _REGISTRY_CONSTANTS,
    _endpoint_identity_digest,
    _scope_digest,
)


PROFILE_V1 = {
    "profile_id": "m7-crawl-reliability-v1",
    "profile_version": "1",
    "inventory_page_size": 50,
    "attachment_page_size": 50,
    "minimum_request_interval_seconds": 3.0,
    "max_response_bytes_per_request": 8388608,
    "max_total_requests_per_run": 50000,
    "max_attempts": 4,
    "base_backoff_seconds": 1.0,
    "max_retry_delay_seconds": 120.0,
    "max_total_retry_delay_seconds": 300.0,
    "jitter": False,
    "max_include_roots": 16,
    "max_pages_per_run": 10000,
    "max_inventory_windows_per_root": 1000,
    "max_inventory_windows_per_run": 4000,
    "max_restriction_targets_per_page": 256,
    "max_restriction_observations_per_run": 25000,
    "max_attachment_windows_per_page": 100,
    "max_attachment_windows_per_run": 10000,
    "max_raw_bytes_per_run": 34359738368,
    "max_raw_artifacts_per_run": 250000,
    "minimum_free_disk_reserve_bytes": 8589934592,
}


class _ProfileThatChangesAfterValidation(Mapping[str, object]):
    """Expose altered values only after the old validator completed."""

    def __init__(self) -> None:
        self._final_field_reads = 0
        self._changed = False

    def __getitem__(self, key: str) -> object:
        if key == "max_raw_artifacts_per_run":
            self._final_field_reads += 1
            value = PROFILE_V1[key]
            if self._final_field_reads == 3:
                self._changed = True
            return 1 if self._changed and self._final_field_reads > 3 else value
        return PROFILE_V1[key]

    def __iter__(self) -> Iterator[str]:
        return iter(PROFILE_V1)

    def __len__(self) -> int:
        return len(PROFILE_V1)


class _SourceConfigThatChangesAfterValidation(ConfluenceSourceConfig):
    """Expose a changed value if the builder rereads the live config."""

    def __init__(self, **values: object) -> None:
        object.__setattr__(self, "_space_key_reads", 0)
        super().__init__(**values)  # type: ignore[arg-type]
        object.__setattr__(self, "_space_key_reads", 0)

    def __getattribute__(self, name: str) -> object:
        if name == "space_key":
            reads = object.__getattribute__(self, "_space_key_reads") + 1
            object.__setattr__(self, "_space_key_reads", reads)
            return "SPACE" if reads == 1 else "CHANGED"
        return super().__getattribute__(name)


def _config(**overrides: object) -> ConfluenceSourceConfig:
    values: dict[str, object] = {
        "source_id": "synthetic-source",
        "space_key": "SPACE",
        "include_roots": (
            ConfluenceIncludeRoot(page_id="20"),
            ConfluenceIncludeRoot(page_id="10", name="Root A"),
        ),
        "exclude_subtrees": (ConfluenceExcludeSubtree(page_id="30"),),
        "include_keywords": ("wiki", "design"),
        "exclude_keywords": ("zeta", "alpha"),
    }
    values.update(overrides)
    return ConfluenceSourceConfig(**values)  # type: ignore[arg-type]


def test_literal_golden_vector() -> None:
    result = build_confluence_crawl_fingerprint("https://example.test/wiki", _config(), PROFILE_V1)
    assert result.value == "59fa059b4a074e90d0895e04b423463095c253b837b23f28d17b158d4b98aa87"


def test_literal_nested_digest_golden_vectors() -> None:
    assert _endpoint_identity_digest("https://example.test/wiki") == (
        "2c02bd07f5819095cb9b344af2c687e551b1f6f7025a718e1d8d0115b3b72d87"
    )
    assert _scope_digest(_config()) == (
        "34ac0985172d6da623f43d0bddce591924bdef83bedfbc3ccd8e22c56f5e5c8b"
    )


def test_reordering_scope_inputs_does_not_change_value() -> None:
    first = build_confluence_crawl_fingerprint("https://EXAMPLE.TEST./wiki///", _config(), PROFILE_V1)
    second = build_confluence_crawl_fingerprint(
        "https://example.test:443/wiki",
        _config(
            include_roots=(ConfluenceIncludeRoot("10", "Root A"), ConfluenceIncludeRoot("20")),
            include_keywords=("design", "wiki", "design"),
            exclude_keywords=("alpha", "zeta", "alpha"),
        ),
        PROFILE_V1,
    )
    assert first == second


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.test/wiki",
        "https://user@example.test/wiki",
        "https://example.test/wiki?x=1",
        "https://example.test/wiki?",
        "https://example.test/wiki#fragment",
        "https://example.test/wiki#",
        " https://example.test/wiki",
        "https://example.test/wiki\n",
        "https:///wiki",
        "https://example.test:bad/wiki",
        "https://example.test:99999/wiki",
    ],
)
def test_endpoint_validation_errors_are_sanitized(endpoint: str) -> None:
    with pytest.raises((TypeError, ValueError)) as error:
        build_confluence_crawl_fingerprint(endpoint, _config(), PROFILE_V1)
    assert str(error.value) == "invalid confluence crawl fingerprint input"


def test_scope_ids_must_be_unique_and_disjoint() -> None:
    with pytest.raises(ValueError):
        build_confluence_crawl_fingerprint(
            "https://example.test", _config(include_roots=(ConfluenceIncludeRoot("10"), ConfluenceIncludeRoot("10"))), PROFILE_V1
        )


@pytest.mark.parametrize("missing", PROFILE_V1)
def test_profile_is_closed_over_required_keys(missing: str) -> None:
    profile = dict(PROFILE_V1)
    del profile[missing]
    with pytest.raises(ValueError):
        build_confluence_crawl_fingerprint("https://example.test", _config(), profile)


def test_profile_rejects_extra_null_bool_integer_and_nonfinite_values() -> None:
    for mutation in (
        lambda p: p.update(extra=1),
        lambda p: p.update(max_attempts=None),
        lambda p: p.update(max_attempts=True),
        lambda p: p.update(base_backoff_seconds=math.inf),
    ):
        profile = dict(PROFILE_V1)
        mutation(profile)
        with pytest.raises((TypeError, ValueError)):
            build_confluence_crawl_fingerprint("https://example.test", _config(), profile)


def test_profile_mapping_is_snapshotted_before_validation_and_hashing() -> None:
    expected = build_confluence_crawl_fingerprint("https://example.test", _config(), PROFILE_V1)
    actual = build_confluence_crawl_fingerprint(
        "https://example.test", _config(), _ProfileThatChangesAfterValidation()
    )
    assert actual == expected


def test_source_config_is_snapshotted_before_validation_and_hashing() -> None:
    expected = build_confluence_crawl_fingerprint("https://example.test", _config(), PROFILE_V1)
    config = _SourceConfigThatChangesAfterValidation(
        source_id="synthetic-source",
        space_key="SPACE",
        include_roots=_config().include_roots,
        exclude_subtrees=_config().exclude_subtrees,
        include_keywords=_config().include_keywords,
        exclude_keywords=_config().exclude_keywords,
    )
    assert build_confluence_crawl_fingerprint("https://example.test", config, PROFILE_V1) == expected
    assert object.__getattribute__(config, "_space_key_reads") == 1


def test_empty_keywords_remain_valid_m5_scope_values() -> None:
    config = _config(include_keywords=("",), exclude_keywords=("",))
    result = build_confluence_crawl_fingerprint("https://example.test", config, PROFILE_V1)
    assert len(result.value) == 64


def test_page_size_mismatch_is_rejected_but_m5_config_remains_valid() -> None:
    config = _config(page_size=25)
    assert config.page_size == 25
    with pytest.raises(ValueError):
        build_confluence_crawl_fingerprint("https://example.test", config, PROFILE_V1)


def test_include_roots_cannot_exceed_the_profile_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(
        include_roots=tuple(ConfluenceIncludeRoot(str(index)) for index in range(17))
    )
    monkeypatch.setattr(
        "knowledgenexus.foundation.domain.models.confluence_crawl_fingerprint._endpoint_identity_digest",
        lambda _: pytest.fail("endpoint digest must not be computed"),
    )
    with pytest.raises(ValueError):
        build_confluence_crawl_fingerprint("https://example.test", config, PROFILE_V1)


def test_fingerprint_registry_constants_cannot_be_mutated() -> None:
    expected = build_confluence_crawl_fingerprint("https://example.test", _config(), PROFILE_V1)
    with pytest.raises(TypeError):
        _REGISTRY_CONSTANTS["fingerprint_contract_version"] = "unapproved"  # type: ignore[index]
    assert build_confluence_crawl_fingerprint("https://example.test", _config(), PROFILE_V1) == expected


def test_path_case_and_approved_scale_profile_change_the_value() -> None:
    lower_path = build_confluence_crawl_fingerprint("https://example.test/wiki", _config(), PROFILE_V1)
    upper_path = build_confluence_crawl_fingerprint("https://example.test/Wiki", _config(), PROFILE_V1)
    scale_profile = dict(PROFILE_V1, profile_id="m7-crawl-scale-acceptance-v2", profile_version="2", max_pages_per_run=100000, max_inventory_windows_per_root=2000)
    scale = build_confluence_crawl_fingerprint("https://example.test/wiki", _config(), scale_profile)
    assert lower_path != upper_path
    assert lower_path != scale


def test_fingerprint_is_opaque_and_constructor_cannot_inject_digest() -> None:
    result = ConfluenceCrawlFingerprintBuilder.build("https://example.test", _config(), PROFILE_V1)
    assert repr(result) == "ConfluenceCrawlFingerprint()"
    assert str(result) == "ConfluenceCrawlFingerprint()"
    with pytest.raises(TypeError):
        ConfluenceCrawlFingerprint(value="0" * 64)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        ConfluenceCrawlFingerprint(digest="0" * 64)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        ConfluenceCrawlFingerprintBuilder.build(  # type: ignore[call-arg]
            "https://example.test", _config(), PROFILE_V1, fingerprint="0" * 64
        )


def test_unicode_is_utf8_and_not_normalized() -> None:
    config = _config(
        include_roots=(ConfluenceIncludeRoot("\u00df", "R\u00f6\u00f6t"),),
        exclude_subtrees=(),
        include_keywords=("\u00df",),
        exclude_keywords=(),
    )
    result = build_confluence_crawl_fingerprint("https://EXAMPLE.TEST/base", config, PROFILE_V1)
    assert len(result.value) == 64
    assert result.value == "12744be623c3e86e1c9af22c49ed709df9bf551bb1eed327a35e906002f3af86"
    assert "example.test" not in repr(result)
    assert "R\\u00f6\\u00f6t" not in repr(result)
