from __future__ import annotations

import copy
import unicodedata
from dataclasses import dataclass


_REFERENCE_INTENT_KINDS = frozenset(
    {"drawio", "image_attachment", "include_page", "page_link"}
)
_REFERENCE_INTENT_STATUSES = frozenset({"unresolved_target", "deferred_mvp"})
_MAX_REFERENCE_IDENTITY_BYTES = 256
_MAX_REFERENCE_INTENTS = 256


def _require_text(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} expects str")
    return value


def _require_identity(value: object, field_name: str) -> str:
    value = _require_text(value, field_name)
    try:
        encoded_length = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} is invalid") from exc
    if not value or encoded_length > _MAX_REFERENCE_IDENTITY_BYTES:
        raise ValueError(f"{field_name} is invalid")
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError(f"{field_name} is not NFC-normalized")
    if any(
        ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F
        for character in value
    ):
        raise ValueError(f"{field_name} contains a control character")
    return value


@dataclass(frozen=True, repr=False)
class NormalizationReferenceIntent:
    """Sanitized, unresolved reference observed during page normalization."""

    ordinal: int
    kind: str
    status: str
    target_identity: str
    placeholder_identity: str

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal <= 0:
            raise ValueError("ordinal must be a positive integer")
        if type(self.kind) is not str or self.kind not in _REFERENCE_INTENT_KINDS:
            raise ValueError("kind is invalid")
        if (
            type(self.status) is not str
            or self.status not in _REFERENCE_INTENT_STATUSES
        ):
            raise ValueError("status is invalid")
        target_identity = _require_identity(self.target_identity, "target_identity")
        placeholder_identity = _require_identity(
            self.placeholder_identity,
            "placeholder_identity",
        )
        if (target_identity == "unknown") != (placeholder_identity == "unknown"):
            raise ValueError("identity values must agree on unknown state")
        if target_identity != "unknown" and target_identity != placeholder_identity:
            raise ValueError("identity values must match")
        if self.kind == "include_page" and self.status != "unresolved_target":
            raise ValueError("include_page intents are unresolved")
        if (
            self.status == "deferred_mvp"
            and self.kind not in {"drawio", "image_attachment", "page_link"}
        ):
            raise ValueError("status is invalid for intent kind")
        if target_identity == "unknown" and self.status != "unresolved_target":
            raise ValueError("unknown identities cannot be deferred")


def _copy_record(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise TypeError(f"{field_name} expects dict")
    copied = copy.deepcopy(value)
    return copied


def _copy_warnings(value: object) -> tuple[dict[str, object], ...]:
    if type(value) is not tuple:
        raise TypeError("warnings expects tuple")
    return tuple(_copy_record(item, "warning") for item in value)


def _copy_intents(value: object) -> tuple[NormalizationReferenceIntent, ...]:
    if type(value) is not tuple:
        raise TypeError("reference_intents expects tuple")
    intents = tuple(value)
    if len(intents) > _MAX_REFERENCE_INTENTS:
        raise ValueError("reference_intents exceeds limit")
    if any(type(item) is not NormalizationReferenceIntent for item in intents):
        raise TypeError("reference_intents contains an invalid item")
    ordinals = tuple(item.ordinal for item in intents)
    if ordinals != tuple(range(1, len(ordinals) + 1)):
        raise ValueError("reference_intents ordinals are not contiguous")
    return intents


@dataclass(frozen=True, repr=False)
class ConfluencePageSource:
    """Trusted source fields extracted from one preserved Confluence page."""

    page_id: str
    title: str
    space_key: str
    source_version: str
    updated_at: str
    storage_xhtml: str
    url: str | None = None


@dataclass(frozen=True, repr=False)
class ConfluenceStorageNormalization:
    """Deterministic storage-format normalization output."""

    normalized_body_text: str
    counters: dict[str, object]
    warnings: tuple[dict[str, object], ...]
    reference_intents: tuple[NormalizationReferenceIntent, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.normalized_body_text, "normalized_body_text")
        object.__setattr__(self, "counters", _copy_record(self.counters, "counters"))
        object.__setattr__(self, "warnings", _copy_warnings(self.warnings))
        object.__setattr__(self, "reference_intents", _copy_intents(self.reference_intents))


@dataclass(frozen=True, repr=False)
class ConfluencePageNormalizationResult:
    """One normalized page and its schema-shaped canonical document."""

    normalized_body_text: str
    canonical_document: dict[str, object]
    counters: dict[str, object]
    warnings: tuple[dict[str, object], ...]
    reference_intents: tuple[NormalizationReferenceIntent, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.normalized_body_text, "normalized_body_text")
        object.__setattr__(
            self,
            "canonical_document",
            _copy_record(self.canonical_document, "canonical_document"),
        )
        object.__setattr__(self, "counters", _copy_record(self.counters, "counters"))
        object.__setattr__(self, "warnings", _copy_warnings(self.warnings))
        object.__setattr__(self, "reference_intents", _copy_intents(self.reference_intents))
