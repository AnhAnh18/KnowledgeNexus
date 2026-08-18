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


def _find_ab_pair(runs: list[dict[str, Any]]) -> tuple[dict | None, dict | None]:
    """Find the latest dense-baseline vs hybrid-rrf pair for A/B comparison."""
    dense_runs = [r for r in runs if "dense" in str(r.get("label", ""))]
    hybrid_runs = [r for r in runs if "hybrid" in str(r.get("label", ""))]
    if not dense_runs or not hybrid_runs:
        return None, None
    dense_runs.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    hybrid_runs.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    return dense_runs[0], hybrid_runs[0]


def render_ab_comparison(run1: dict[str, Any], run2: dict[str, Any]) -> list[str]:
    """Render an A/B comparison section for two runs."""
    def _m(run: dict, section: str, key: str) -> float | None:
        block = run.get(section)
        if not isinstance(block, dict):
            return None
        v = block.get(key)
        return float(v) if v is not None else None

    def _fmt(v: float | None) -> str:
        return "—" if v is None else f"{v:.3f}"

    def _fmt_delta(a: float | None, b: float | None) -> str:
        if a is None or b is None:
            return "—"
        d = b - a
        sign = "+" if d >= 0 else ""
        return f"{b:.3f} ({sign}{d:.3f})"

    lines = [
        "",
        "## A/B Comparison (latest dense vs hybrid)",
        "",
        f"**Run 1:** `{run1.get('label')}` — {str(run1.get('created_at',''))[:19]}  ",
        f"**Run 2:** `{run2.get('label')}` — {str(run2.get('created_at',''))[:19]}",
        "",
        "| Metric | Dense | Hybrid | Delta |",
        "|--------|-------|--------|-------|",
    ]

    for label, section, key in [
        ("L1 Hit@5", "layer1", "hit_at_5"),
        ("L1 Hit@10", "layer1", "hit_at_10"),
        ("L1 MRR", "layer1", "mrr"),
        ("L2 Hit@5", "layer2", "hit_at_5"),
        ("L2 Hit@10", "layer2", "hit_at_10"),
        ("L2 MRR", "layer2", "mrr"),
    ]:
        a, b = _m(run1, section, key), _m(run2, section, key)
        lines.append(f"| {label} | {_fmt(a)} | {_fmt_delta(a, b)} | |")

    # Per-case highlights for hybrid-critical queries
    per1 = run1.get("per_case_layer1") or []
    per2 = run2.get("per_case_layer1") or []
    if per1 and per2:
        cm1 = {c["case_id"]: c for c in per1}
        cm2 = {c["case_id"]: c for c in per2}
        common = sorted(set(cm1) & set(cm2))
        improved = [cid for cid in common
                    if cm2[cid].get("mrr", 0) > cm1[cid].get("mrr", 0)]
        regressed = [cid for cid in common
                     if cm2[cid].get("mrr", 0) < cm1[cid].get("mrr", 0)]
        if improved or regressed:
            lines.extend([
                "",
                f"**Per-case:** {len(improved)} improved, {len(regressed)} regressed, {len(common)} total",
            ])
            if improved:
                lines.append(f"- Improved: {', '.join(improved)}")
            if regressed:
                lines.append(f"- Regressed: {', '.join(regressed)}")

    # Decision
    h1 = _m(run1, "layer1", "hit_at_10")
    h2 = _m(run2, "layer1", "hit_at_10")
    lines.extend(["", "## Decision", ""])
    if h1 is not None and h2 is not None:
        delta = h2 - h1
        if delta > 0.02:
            lines.append("✅ **Hybrid wins** — L1 Hit@10 improved significantly.")
        elif delta < -0.02:
            lines.append("❌ **Hybrid loses** — L1 Hit@10 dropped. Keep dense.")
        else:
            lines.append("➖ **No significant change** — L1 Hit@10 roughly equal. Check per-case for tag-specific improvements.")
    else:
        lines.append("⚠️ Insufficient data for decision.")

    lines.append("")
    return lines


def update_leaderboard(results_dir: Path) -> Path:
    runs = load_all_runs(results_dir)
    text = render_leaderboard(runs)

    # Append A/B comparison if we have a dense/hybrid pair
    run1, run2 = _find_ab_pair(runs)
    if run1 and run2:
        ab_lines = render_ab_comparison(run1, run2)
        text += "\n".join(ab_lines)

    out = results_dir / "LEADERBOARD.md"
    results_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out
