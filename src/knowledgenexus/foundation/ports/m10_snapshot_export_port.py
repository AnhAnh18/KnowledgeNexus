"""Ports for the generic M10 exporter to consume the shared M3 seams."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class M10StagingWriterPort(Protocol):
    def write(self, **kwargs: object) -> dict[str, object]: ...


class M10StagingCompleterPort(Protocol):
    def complete(self, **kwargs: object) -> dict[str, object]: ...


class M10PublisherPort(Protocol):
    def publish(self, **kwargs: object) -> Path: ...


__all__ = ["M10StagingWriterPort", "M10StagingCompleterPort", "M10PublisherPort"]
