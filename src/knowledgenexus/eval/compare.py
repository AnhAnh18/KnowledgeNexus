"""Persist runs and rebuild LEADERBOARD.md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from knowledgenexus.eval.models import EvalRunResult


def save_run(result: EvalRunResult, results_dir: Path) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    out = results_dir / f"{result.run_id}.json"
    out.write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out


def load_all_runs(results_dir: Path) -> list[dict[str, Any]]:
    if not results_dir.is_dir():
        return []
    runs: list[dict[str, Any]] = []
    for path in sorted(results_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(payload, dict) and "run_id" in payload:
            runs.append(payload)
    runs.sort(key=lambda r: str(r.get("created_at", "")))
    return runs


def render_leaderboard(runs: list[dict[str, Any]]) -> str:
    lines = [
        "# Eval leaderboard (2-layer)",
        "",
        "L1 = oracle `search_query` → retrieve.  ",
        "L2 = Skill-like `plan(user_question)` → retrieve.  ",
        "Gap = L1 − L2 (Skill/query formulation loss).",
        "",
        "| When | Label | L1 Hit@10 | L2 Hit@10 | Gap@10 | L1 MRR | L2 MRR | N |",
        "|------|-------|-----------|-----------|--------|--------|--------|---|",
    ]

    def _fmt(metrics: dict[str, Any] | None, key: str) -> str:
        if not metrics:
            return "—"
        value = metrics.get(key)
        if value is None:
            return "—"
        return f"{float(value):.3f}"

    for run in runs:
        l1 = run.get("layer1")
        l2 = run.get("layer2")
        gap = run.get("gap") or {}
        n = 0
        if isinstance(l1, dict):
            n = int(l1.get("n_cases") or 0)
        elif isinstance(l2, dict):
            n = int(l2.get("n_cases") or 0)
        gap10 = gap.get("hit_at_10")
        gap_s = f"{float(gap10):.3f}" if gap10 is not None else "—"
        lines.append(
            "| {when} | {label} | {l1h} | {l2h} | {gap} | {l1m} | {l2m} | {n} |".format(
                when=str(run.get("created_at", ""))[:19],
                label=run.get("label", ""),
                l1h=_fmt(l1 if isinstance(l1, dict) else None, "hit_at_10"),
                l2h=_fmt(l2 if isinstance(l2, dict) else None, "hit_at_10"),
                gap=gap_s,
                l1m=_fmt(l1 if isinstance(l1, dict) else None, "mrr"),
                l2m=_fmt(l2 if isinstance(l2, dict) else None, "mrr"),
                n=n,
            )
        )

    if len(runs) >= 2:
        prev, curr = runs[-2], runs[-1]
        lines.extend(["", "## Latest vs previous", ""])
        lines.append(_delta_line("L1 Hit@10", prev, curr, "layer1", "hit_at_10"))
        lines.append(_delta_line("L2 Hit@10", prev, curr, "layer2", "hit_at_10"))
        lines.append(_delta_line("Gap@10", prev, curr, "gap", "hit_at_10", gap_mode=True))
        lines.append(
            f"- Labels: `{prev.get('label')}` → `{curr.get('label')}`"
        )

    lines.append("")
    return "\n".join(lines)


def _delta_line(
    title: str,
    prev: dict[str, Any],
    curr: dict[str, Any],
    section: str,
    key: str,
    *,
    gap_mode: bool = False,
) -> str:
    def _get(run: dict[str, Any]) -> float | None:
        block = run.get(section)
        if not isinstance(block, dict):
            return None
        value = block.get(key)
        return float(value) if value is not None else None

    a, b = _get(prev), _get(curr)
    if a is None or b is None:
        return f"- {title}: —"
    delta = b - a
    sign = "+" if delta >= 0 else ""
    return f"- {title}: {b:.3f} ({sign}{delta:.3f})"


def update_leaderboard(results_dir: Path) -> Path:
    runs = load_all_runs(results_dir)
    text = render_leaderboard(runs)
    out = results_dir / "LEADERBOARD.md"
    results_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out
