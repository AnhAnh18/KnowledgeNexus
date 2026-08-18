"""CLI runner: ``uv run kn-eval --layer all --label baseline``."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from eval.compare import save_run, update_leaderboard
from eval.config import load_eval_config
from eval.layer1_retrieval import run_layer1
from eval.loader import GoldenLoadError, load_golden_cases
from eval.metrics import compute_gap
from eval.models import EvalRunResult


def _git_sha(repo_root: Path) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def run_eval(
    *,
    layer: str,
    label: str,
    config_path: Path | str | None = None,
    golden_path: Path | str | None = None,
) -> EvalRunResult:
    config = load_eval_config(config_path)
    golden = Path(golden_path) if golden_path else config.resolved_golden_path
    cases = load_golden_cases(golden)

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    safe_label = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)[:64]
    run_id = f"{stamp}_{safe_label}"

    layer1_metrics = None
    layer2_metrics = None
    per1: list = []
    per2: list = []

    if layer in ("1", "all"):
        layer1_metrics, per1 = run_layer1(cases, config)
    if layer in ("2", "all"):
        from eval.layer2_agent import run_layer2
        layer2_metrics, per2 = run_layer2(cases, config)

    result = EvalRunResult(
        run_id=run_id,
        label=label,
        created_at=now.isoformat(),
        config={
            "layer": layer,
            "top_k": config.top_k,
            "score_threshold": config.score_threshold,
            "api_base_url": config.api_base_url,
            "golden_path": str(golden),
            "golden_count": len(cases),
            "match_on": config.match_on,
            "retrieval_mode": config.retrieval_mode,
            "git_sha": _git_sha(config.repo_root),
        },
        layer1=layer1_metrics,
        layer2=layer2_metrics,
        gap=compute_gap(layer1_metrics, layer2_metrics),
        per_case_layer1=per1,
        per_case_layer2=per2,
    )

    out = save_run(result, config.resolved_results_dir)
    board = update_leaderboard(config.resolved_results_dir)
    _print_summary(result, out, board)
    return result


def _print_summary(result: EvalRunResult, out: Path, board: Path) -> None:
    print(f"Run: {result.run_id}")
    print(f"Saved: {out}")
    print(f"Leaderboard: {board}")
    if result.layer1:
        print(
            f"L1  Hit@5={result.layer1.hit_at_5:.3f}  "
            f"Hit@10={result.layer1.hit_at_10:.3f}  "
            f"MRR={result.layer1.mrr:.3f}  "
            f"n={result.layer1.n_cases}"
        )
    if result.layer2:
        print(
            f"L2  Hit@5={result.layer2.hit_at_5:.3f}  "
            f"Hit@10={result.layer2.hit_at_10:.3f}  "
            f"MRR={result.layer2.mrr:.3f}  "
            f"n={result.layer2.n_cases}"
        )
    if result.gap:
        print(
            f"Gap Hit@5={result.gap['hit_at_5']:.3f}  "
            f"Hit@10={result.gap['hit_at_10']:.3f}  "
            f"MRR={result.gap['mrr']:.3f}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kn-eval",
        description="Two-layer eval: retrieval (L1) + agent/Skill query path (L2)",
    )
    parser.add_argument(
        "--layer",
        choices=("1", "2", "all"),
        default="all",
        help="Which layer(s) to run (default: all)",
    )
    parser.add_argument(
        "--label",
        required=True,
        help="Short label for this run (e.g. baseline, skill-v2)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config/eval.yaml (optional)",
    )
    parser.add_argument(
        "--golden",
        default=None,
        help="Override golden JSONL path",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        run_eval(
            layer=args.layer,
            label=args.label,
            config_path=args.config,
            golden_path=args.golden,
        )
    except GoldenLoadError as e:
        print(f"Golden error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Eval failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
