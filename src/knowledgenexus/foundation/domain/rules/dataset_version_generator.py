from __future__ import annotations

from datetime import datetime, timezone


class DatasetVersionGenerator:
    """Deterministic dataset_version formatting for Foundation export snapshots."""

    @staticmethod
    def generate(*, instant: datetime) -> str:
        if not isinstance(instant, datetime):
            raise TypeError("DatasetVersionGenerator.instant expects datetime")

        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError(
                "DatasetVersionGenerator.instant must be timezone-aware"
            )

        utc_instant = instant.astimezone(timezone.utc)

        return (
            f"v{utc_instant.year:04d}"
            f"{utc_instant.month:02d}"
            f"{utc_instant.day:02d}-"
            f"{utc_instant.hour:02d}"
            f"{utc_instant.minute:02d}"
            f"{utc_instant.second:02d}-"
            f"{utc_instant.microsecond:06d}Z"
        )
