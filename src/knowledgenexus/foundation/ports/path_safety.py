"""Cross-platform validation for externally supplied plain directory chains."""
from __future__ import annotations

import os
import stat
from pathlib import Path


def _is_reparse(details: os.stat_result) -> bool:
    return bool(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) and details.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def require_plain_directory_chain(path: Path) -> None:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError("directory path is invalid")
    for component in reversed((path, *path.parents)):
        details = os.lstat(component)
        if _is_reparse(details) or stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
            raise ValueError("directory path is not plain")


def require_plain_file(path: Path) -> None:
    details = os.lstat(path)
    if _is_reparse(details) or stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
        raise ValueError("file is not plain")


__all__ = ["require_plain_directory_chain", "require_plain_file"]
