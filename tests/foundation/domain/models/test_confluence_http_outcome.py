from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.models.confluence_http_outcome import (
    ConfluenceHttpFailureKind,
    ConfluenceHttpFailureMetadata,
    ConfluenceRetryAfterMetadata,
    ConfluenceRetryAfterState,
    confluence_retry_after_absent,
    confluence_retry_after_ignored,
    confluence_retry_after_valid,
)


def test_absent_accepts_none_delay() -> None:
    metadata = confluence_retry_after_absent()
    assert metadata.state is ConfluenceRetryAfterState.ABSENT
    assert metadata.delay_seconds is None


def test_ignored_accepts_none_delay() -> None:
    metadata = confluence_retry_after_ignored()
    assert metadata.state is ConfluenceRetryAfterState.IGNORED
    assert metadata.delay_seconds is None


def test_valid_accepts_zero_int_delay() -> None:
    metadata = confluence_retry_after_valid(0)
    assert metadata.delay_seconds == 0


def test_valid_accepts_zero_float_delay() -> None:
    metadata = confluence_retry_after_valid(0.0)
    assert metadata.delay_seconds == 0.0


def test_valid_rejects_negative_delay() -> None:
    with pytest.raises(ValueError):
        confluence_retry_after_valid(-1)


@pytest.mark.parametrize("delay", (float("nan"), float("inf"), float("-inf")))
def test_valid_rejects_non_finite_float(delay: float) -> None:
    with pytest.raises(ValueError):
        confluence_retry_after_valid(delay)


def test_valid_rejects_bool_delay() -> None:
    with pytest.raises(TypeError):
        confluence_retry_after_valid(True)


def test_valid_rejects_string_delay() -> None:
    with pytest.raises(TypeError):
        confluence_retry_after_valid("30")  # type: ignore[arg-type]


def test_absent_rejects_non_none_delay() -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryAfterMetadata(
            state=ConfluenceRetryAfterState.ABSENT,
            delay_seconds=1,
        )


def test_ignored_rejects_non_none_delay() -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryAfterMetadata(
            state=ConfluenceRetryAfterState.IGNORED,
            delay_seconds=1,
        )


def test_rejects_non_enum_state() -> None:
    with pytest.raises(TypeError):
        ConfluenceRetryAfterMetadata(state="absent", delay_seconds=None)  # type: ignore[arg-type]


def test_retry_after_repr_hides_state_and_delay() -> None:
    metadata = confluence_retry_after_valid(30)
    rendered = repr(metadata)
    assert "30" not in rendered
    assert "valid" not in rendered
    assert rendered == "ConfluenceRetryAfterMetadata()"


def test_retry_after_equality_is_value_based() -> None:
    assert confluence_retry_after_valid(30) == confluence_retry_after_valid(30)
    assert confluence_retry_after_absent() == confluence_retry_after_absent()
    assert confluence_retry_after_valid(30) != confluence_retry_after_valid(31)


def _http_status_metadata(
    *,
    http_status: object = 500,
    retry_after: ConfluenceRetryAfterMetadata | None = None,
) -> ConfluenceHttpFailureMetadata:
    return ConfluenceHttpFailureMetadata(
        kind=ConfluenceHttpFailureKind.HTTP_STATUS,
        http_status=http_status,  # type: ignore[arg-type]
        retry_after=retry_after or confluence_retry_after_absent(),
    )


def test_http_status_without_status_rejected() -> None:
    with pytest.raises(TypeError):
        _http_status_metadata(http_status=None)


def test_http_status_with_bool_status_rejected() -> None:
    with pytest.raises(TypeError):
        _http_status_metadata(http_status=True)


@pytest.mark.parametrize("status", (300, 399))
def test_http_status_with_3xx_rejected(status: int) -> None:
    with pytest.raises(ValueError):
        _http_status_metadata(http_status=status)


def test_http_status_accepts_ignored_or_valid_retry_after() -> None:
    _http_status_metadata(retry_after=confluence_retry_after_ignored())
    _http_status_metadata(retry_after=confluence_retry_after_valid(1))


def test_redirect_policy_failure_with_non_3xx_rejected() -> None:
    with pytest.raises(ValueError):
        ConfluenceHttpFailureMetadata(
            kind=ConfluenceHttpFailureKind.REDIRECT_POLICY_FAILURE,
            http_status=200,
            retry_after=confluence_retry_after_absent(),
        )


def test_redirect_policy_failure_requires_absent_retry_after() -> None:
    with pytest.raises(ValueError):
        ConfluenceHttpFailureMetadata(
            kind=ConfluenceHttpFailureKind.REDIRECT_POLICY_FAILURE,
            http_status=302,
            retry_after=confluence_retry_after_ignored(),
        )


def test_redirect_policy_failure_accepts_3xx_with_absent_retry_after() -> None:
    ConfluenceHttpFailureMetadata(
        kind=ConfluenceHttpFailureKind.REDIRECT_POLICY_FAILURE,
        http_status=302,
        retry_after=confluence_retry_after_absent(),
    )


def test_non_http_kind_carrying_status_rejected() -> None:
    with pytest.raises(ValueError):
        ConfluenceHttpFailureMetadata(
            kind=ConfluenceHttpFailureKind.MALFORMED_JSON,
            http_status=500,
            retry_after=confluence_retry_after_absent(),
        )


@pytest.mark.parametrize(
    "retry_after",
    (confluence_retry_after_valid(1), confluence_retry_after_ignored()),
)
def test_non_http_kind_carrying_non_absent_retry_after_rejected(
    retry_after: ConfluenceRetryAfterMetadata,
) -> None:
    with pytest.raises(ValueError):
        ConfluenceHttpFailureMetadata(
            kind=ConfluenceHttpFailureKind.MALFORMED_JSON,
            http_status=None,
            retry_after=retry_after,
        )


def test_metadata_rejects_non_enum_kind() -> None:
    with pytest.raises(TypeError):
        ConfluenceHttpFailureMetadata(
            kind="http_status",  # type: ignore[arg-type]
            http_status=500,
            retry_after=confluence_retry_after_absent(),
        )


def test_metadata_rejects_non_retry_after_instance() -> None:
    with pytest.raises(TypeError):
        ConfluenceHttpFailureMetadata(
            kind=ConfluenceHttpFailureKind.MALFORMED_JSON,
            http_status=None,
            retry_after=None,  # type: ignore[arg-type]
        )


def test_failure_metadata_repr_hides_values() -> None:
    metadata = _http_status_metadata()
    rendered = repr(metadata)
    assert "500" not in rendered
    assert "http_status" not in rendered
    assert rendered == "ConfluenceHttpFailureMetadata()"
