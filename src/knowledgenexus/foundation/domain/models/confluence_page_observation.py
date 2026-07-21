from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, repr=False)
class RawHttpObservation:
    """An HTTP status and its exact response-body bytes."""

    status_code: int
    body: bytes

    def __post_init__(self) -> None:
        if isinstance(self.status_code, bool) or not isinstance(self.status_code, int):
            raise TypeError("status_code expects an integer")
        if self.status_code < 100 or self.status_code > 599:
            raise ValueError("status_code must be a valid HTTP status")
        if not isinstance(self.body, bytes):
            raise TypeError("body expects bytes")

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


@dataclass(frozen=True, order=True)
class AttachmentMetadataRequest:
    """A validated attachment metadata request window."""

    start: int
    limit: int

    def __post_init__(self) -> None:
        if isinstance(self.start, bool) or not isinstance(self.start, int):
            raise TypeError("start expects an integer")
        if self.start < 0:
            raise ValueError("start must be non-negative")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise TypeError("limit expects an integer")
        if self.limit <= 0:
            raise ValueError("limit must be positive")


@dataclass(frozen=True, repr=False)
class ParsedAttachmentMetadataWindow:
    """Normalized metadata plus the server-observed next request."""

    attachments: tuple[dict[str, object], ...]
    next_request: AttachmentMetadataRequest | None

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"
