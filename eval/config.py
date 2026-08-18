"""Eval configuration loader."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from eval.models import MatchOn


@dataclass(frozen=True)
class EvalConfig:
    top_k: int = 10
    score_threshold: float = 0.0
    api_base_url: str = "http://localhost:8000"
    golden_path: Path = Path("data/eval/golden/queries.jsonl")
    results_dir: Path = Path("data/eval/results")
    match_on: MatchOn = "source_id"
    repo_root: Path = Path(".")
    retrieval_mode: str = "dense"

    @property
    def resolved_golden_path(self) -> Path:
        path = self.golden_path
        return path if path.is_absolute() else self.repo_root / path

    @property
    def resolved_results_dir(self) -> Path:
        path = self.results_dir
        return path if path.is_absolute() else self.repo_root / path


def find_repo_root(start: Path | None = None) -> Path:
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
            return candidate
    return cur


def load_eval_config(
    config_path: Path | str | None = None,
    *,
    repo_root: Path | None = None,
) -> EvalConfig:
    root = repo_root or find_repo_root()
    path = Path(config_path) if config_path else root / "config" / "eval.yaml"
    raw: dict[str, Any] = {}
    if path.is_file():
        with path.open(encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Invalid eval config (expected mapping): {path}")
        raw = loaded

    match_on_raw = str(raw.get("match_on", "source_id"))
    if match_on_raw not in ("document_id", "chunk_id", "source_id"):
        raise ValueError("match_on must be 'document_id', 'chunk_id', or 'source_id'")
    match_on: MatchOn = match_on_raw  # type: ignore[assignment]

    api_base = os.environ.get(
        "KNOWLEDGENEXUS_API_URL",
        str(raw.get("api_base_url", "http://localhost:8000")),
    )

    retrieval_mode = os.environ.get(
        "KNOWLEDGENEXUS_RETRIEVAL_MODE",
        str(raw.get("retrieval_mode", "dense")),
    )

    return EvalConfig(
        top_k=int(raw.get("top_k", 10)),
        score_threshold=float(raw.get("score_threshold", 0.0)),
        api_base_url=api_base.rstrip("/"),
        golden_path=Path(str(raw.get("golden_path", "data/eval/golden/queries.jsonl"))),
        results_dir=Path(str(raw.get("results_dir", "data/eval/results"))),
        match_on=match_on,
        repo_root=root,
        retrieval_mode=retrieval_mode,
    )
