from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from knowledgenexus.foundation.domain.models.confluence_retry_policy import (
    ConfluenceRetryPolicyProfile,
)


CONTRACT_ROOT = Path(__file__).resolve().parents[3] / "contracts" / "foundation"


def _load_profile(name: str) -> dict[str, object]:
    with (CONTRACT_ROOT / name).open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    assert isinstance(loaded, dict)
    return loaded


def test_scale_acceptance_profile_is_a_narrow_nonproduction_variant() -> None:
    production = _load_profile("crawl_reliability_profile.yaml")
    scale = _load_profile("crawl_reliability_scale_profile.yaml")

    assert set(scale) == set(production)
    assert {
        key: value
        for key, value in scale.items()
        if production[key] != value
    } == {
        "profile_id": "m7-crawl-scale-acceptance-v2",
        "profile_version": "2",
        "max_pages_per_run": 100000,
        "max_inventory_windows_per_root": 2000,
    }


def test_scale_profile_cannot_redefine_the_approved_b2_retry_binding() -> None:
    production = _load_profile("crawl_reliability_profile.yaml")
    scale = _load_profile("crawl_reliability_scale_profile.yaml")

    # The scale profile changes inventory caps only; retry policy remains v1.
    assert ConfluenceRetryPolicyProfile.from_mapping(production).profile_version == "1"
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyProfile.from_mapping(scale)

    retry_policy_keys = {
        "max_total_requests_per_run",
        "max_attempts",
        "base_backoff_seconds",
        "max_retry_delay_seconds",
        "max_total_retry_delay_seconds",
        "jitter",
    }
    assert {key: scale[key] for key in retry_policy_keys} == {
        key: production[key] for key in retry_policy_keys
    }
