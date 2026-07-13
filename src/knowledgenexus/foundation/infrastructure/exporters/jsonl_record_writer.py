from __future__ import annotations

import json
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TextIO


class JsonlRecordWriter:
    @staticmethod
    def write(
        *,
        path: Path,
        records: Iterable[Mapping[str, object]],
    ) -> int:
        if not path.parent.is_dir():
            raise FileNotFoundError(f"Parent directory does not exist: {path.parent}")

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="\n",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                count = 0
                for record in records:
                    JsonlRecordWriter._write_record(temp_file, record)
                    count += 1

            temp_path.replace(path)
            return count
        except Exception:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    @staticmethod
    def _write_record(
        file_handle: TextIO,
        record: Mapping[str, object],
    ) -> None:
        if not isinstance(record, Mapping):
            raise TypeError("JSONL record must be a mapping")

        plain_record = dict(record)

        for key in plain_record:
            if not isinstance(key, str):
                raise TypeError("JSONL record top-level keys must be strings")

        json.dump(
            plain_record,
            file_handle,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        file_handle.write("\n")
