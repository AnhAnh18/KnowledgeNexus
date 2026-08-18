#!/usr/bin/env python3
"""Compare two eval runs and generate an A/B comparison report.

Usage:
    python scripts/compare_eval_results.py --run1 dense --run2 hybrid --output data/eval/results/ab_comparison.md
    python scripts/compare_eval_results.py --label1 dense-baseline --label2 hybrid-rrf
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add eval to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from compare import load_all_runs


def find_run_by_label(runs: list[dict], label: str) -> dict | None:
    """Find the most recent run matching a label (partial match)."""
    matches = [r for r in runs if label in str(r.get("label", ""))]
    if not matches:
        return None
    # Return the latest match
    matches.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    return matches[0]


def find_run_by_id(runs: list[dict], run_id: str) -> dict | None:
    """Find a run by run_id (partial match)."""
    for r in runs:
        if run_id in str(r.get("run_id", "")):
            return r
    return None


def extract_metrics(run: dict) -> dict:
    """Extract key metrics from a run."""
    l1 = run.get("layer1") or {}
    l2 = run.get("layer2") or {}
    gap = run.get("gap") or {}
    config = run.get("config") or {}
    return {
        "label": run.get("label", "?"),
        "run_id": run.get("run_id", "?"),
        "created_at": str(run.get("created_at", "?"))[:19],
        "retrieval_mode": config.get("retrieval_mode", "dense"),
        "l1_hit_at_5": l1.get("hit_at_5"),
        "l1_hit_at_10": l1.get("hit_at_10"),
        "l1_mrr": l1.get("mrr"),
        "l1_n": l1.get("n_cases"),
        "l2_hit_at_5": l2.get("hit_at_5"),
        "l2_hit_at_10": l2.get("hit_at_10"),
        "l2_mrr": l2.get("mrr"),
        "gap_hit_at_10": gap.get("hit_at_10"),
        "gap_mrr": gap.get("mrr"),
    }


def fmt(val, suffix: str = "") -> str:
    if val is None:
        return "—"
    return f"{float(val):.3f}{suffix}"


def fmt_delta(a, b) -> str:
    if a is None or b is None:
        return "—"
    delta = float(b) - float(a)
    sign = "+" if delta >= 0 else ""
    return f"{float(b):.3f} ({sign}{delta:.3f})"


def generate_report(run1: dict, run2: dict) -> str:
    m1 = extract_metrics(run1)
    m2 = extract_metrics(run2)

    lines = [
        "# A/B Comparison Report",
        "",
        f"**Run 1:** `{m1['label']}` ({m1['retrieval_mode']}) — {m1['created_at']}",
        f"**Run 2:** `{m2['label']}` ({m2['retrieval_mode']}) — {m2['created_at']}",
        "",
        "## Summary",
        "",
        "| Metric | Run 1 (dense) | Run 2 (hybrid) | Delta |",
        "|--------|---------------|----------------|-------|",
        f"| L1 Hit@5 | {fmt(m1['l1_hit_at_5'])} | {fmt_delta(m1['l1_hit_at_5'], m2['l1_hit_at_5'])} | |",
        f"| L1 Hit@10 | {fmt(m1['l1_hit_at_10'])} | {fmt_delta(m1['l1_hit_at_10'], m2['l1_hit_at_10'])} | |",
        f"| L1 MRR | {fmt(m1['l1_mrr'])} | {fmt_delta(m1['l1_mrr'], m2['l1_mrr'])} | |",
        f"| L2 Hit@5 | {fmt(m1['l2_hit_at_5'])} | {fmt_delta(m1['l2_hit_at_5'], m2['l2_hit_at_5'])} | |",
        f"| L2 Hit@10 | {fmt(m1['l2_hit_at_10'])} | {fmt_delta(m1['l2_hit_at_10'], m2['l2_hit_at_10'])} | |",
        f"| L2 MRR | {fmt(m1['l2_mrr'])} | {fmt_delta(m1['l2_mrr'], m2['l2_mrr'])} | |",
        f"| Gap@10 | {fmt(m1['gap_hit_at_10'])} | {fmt_delta(m1['gap_hit_at_10'], m2['gap_hit_at_10'])} | |",
        f"| Gap MRR | {fmt(m1['gap_mrr'])} | {fmt_delta(m1['gap_mrr'], m2['gap_mrr'])} | |",
        "",
    ]

    # Per-case comparison (L1)
    per1 = run1.get("per_case_layer1") or []
    per2 = run2.get("per_case_layer1") or []

    if per1 and per2:
        case_map1 = {c["case_id"]: c for c in per1}
        case_map2 = {c["case_id"]: c for c in per2}

        common_ids = sorted(set(case_map1.keys()) & set(case_map2.keys()))
        if common_ids:
            lines.extend([
                "## Per-case L1 comparison",
                "",
                "| Case ID | Dense Hit@10 | Hybrid Hit@10 | Dense MRR | Hybrid MRR | Changed |",
                "|---------|---------------|----------------|-----------|------------|---------|",
            ])

            improved = 0
            regressed = 0
            for cid in common_ids:
                c1 = case_map1[cid]
                c2 = case_map2[cid]
                h1 = "✅" if c1.get("hit_at_10") else "❌"
                h2 = "✅" if c2.get("hit_at_10") else "❌"
                mrr1 = c1.get("mrr", 0.0)
                mrr2 = c2.get("mrr", 0.0)
                changed = ""
                if c2.get("hit_at_10") and not c1.get("hit_at_10"):
                    changed = "⬆️ improved"
                    improved += 1
                elif not c2.get("hit_at_10") and c1.get("hit_at_10"):
                    changed = "⬇️ regressed"
                    regressed += 1
                lines.append(
                    f"| {cid} | {h1} | {h2} | {mrr1:.3f} | {mrr2:.3f} | {changed} |"
                )

            lines.extend([
                "",
                f"**Improved:** {improved} cases  ",
                f"**Regressed:** {regressed} cases",
                "",
            ])

    # Decision
    lines.extend([
        "## Decision",
        "",
    ])

    h1_dense = m1["l1_hit_at_10"]
    h1_hybrid = m2["l1_hit_at_10"]
    if h1_dense is not None and h1_hybrid is not None:
        delta = float(h1_hybrid) - float(h1_dense)
        if delta > 0.02:
            lines.append("✅ **Hybrid wins** — L1 Hit@10 improved significantly.")
        elif delta < -0.02:
            lines.append("❌ **Hybrid loses** — L1 Hit@10 dropped significantly. Keep dense.")
        else:
            lines.append("➖ **No significant change** — L1 Hit@10 roughly equal. Check per-case for tag-specific improvements.")
    else:
        lines.append("⚠️ Insufficient data for decision.")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two eval runs (A/B)")
    parser.add_argument(
        "--label1",
        default=None,
        help="Label of run 1 (partial match, e.g. 'dense-baseline')",
    )
    parser.add_argument(
        "--label2",
        default=None,
        help="Label of run 2 (partial match, e.g. 'hybrid-rrf')",
    )
    parser.add_argument(
        "--run1",
        default=None,
        help="Run ID of run 1 (partial match)",
    )
    parser.add_argument(
        "--run2",
        default=None,
        help="Run ID of run 2 (partial match)",
    )
    parser.add_argument(
        "--results-dir",
        default="data/eval/results",
        help="Results directory (default: data/eval/results)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file (default: print to stdout)",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    runs = load_all_runs(results_dir)

    if not runs:
        print(f"No runs found in {results_dir}")
        return 1

    # Find run 1
    run1 = None
    if args.run1:
        run1 = find_run_by_id(runs, args.run1)
    elif args.label1:
        run1 = find_run_by_label(runs, args.label1)

    if run1 is None:
        print(f"Run 1 not found. Available runs:")
        for r in runs:
            print(f"  {r.get('run_id')} | {r.get('label')}")
        return 1

    # Find run 2
    run2 = None
    if args.run2:
        run2 = find_run_by_id(runs, args.run2)
    elif args.label2:
        run2 = find_run_by_label(runs, args.label2)

    if run2 is None:
        print(f"Run 2 not found. Available runs:")
        for r in runs:
            print(f"  {r.get('run_id')} | {r.get('label')}")
        return 1

    report = generate_report(run1, run2)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"Report saved to {out_path}")
    else:
        sys.stdout.buffer.write(report.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")


    # Always update LEADERBOARD.md with A/B comparison appended
    from compare import update_leaderboard
    lb = update_leaderboard(results_dir)
    print(f"Leaderboard updated: {lb}")

    return 0



if __name__ == "__main__":
    raise SystemExit(main())
