#!/usr/bin/env python
"""Run dense vs hybrid A/B eval in one go.

Usage:
    python scripts/run_hybrid_ab_eval.py

This script:
  1. Starts the API with dense collection, runs L1 eval (label: dense-baseline)
  2. Restarts the API with hybrid collection, runs L1 eval (label: hybrid-rrf)
  3. Generates ab_comparison.md
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
PYTHON = sys.executable

DENSE_COLLECTION = "knowledgenexus_dense_test"
HYBRID_COLLECTION = "knowledgenexus_hybrid_test"
API_URL = "http://127.0.0.1:8000"
HEALTH_ENDPOINT = f"{API_URL}/api/v1/health"


def set_env(collection: str, mode: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR)
    env["QDRANT_COLLECTION"] = collection
    env["RETRIEVAL_MODE"] = mode
    env["KNOWLEDGENEXUS_API_URL"] = API_URL
    env["KNOWLEDGENEXUS_RETRIEVAL_MODE"] = mode
    return env


def wait_for_api(timeout: int = 120) -> bool:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_ENDPOINT, timeout=5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def kill_port(port: int) -> None:
    """Kill any process listening on the given port (Windows)."""
    try:
        result = subprocess.run(
            [
                "powershell", "-Command",
                f"Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue "
                f"| Select-Object -ExpandProperty OwningProcess "
                f"| ForEach-Object {{ Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        pass


def start_api(env: dict[str, str]) -> subprocess.Popen:
    proc = subprocess.Popen(
        [
            PYTHON, "-m", "uvicorn",
            "knowledgenexus.presentation.api.app:app",
            "--host", "127.0.0.1",
            "--port", "8000",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(REPO_ROOT),
    )
    return proc


def stop_api(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    kill_port(8000)
    time.sleep(2)


def run_eval(label: str, mode: str) -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR)
    env["KNOWLEDGENEXUS_API_URL"] = API_URL
    env["KNOWLEDGENEXUS_RETRIEVAL_MODE"] = mode
    result = subprocess.run(
        [PYTHON, "-m", "knowledgenexus.eval.runner", "--layer", "1", "--label", label],
        env=env,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr, file=sys.stderr)
    return result.returncode


def main() -> int:
    # ── Phase 1: Dense ──
    print("=" * 60)
    print("  Phase 1: Dense baseline eval")
    print("=" * 60)

    print(f"\nStarting API with collection={DENSE_COLLECTION}, mode=dense ...")
    env_dense = set_env(DENSE_COLLECTION, "dense")
    api_proc = start_api(env_dense)

    print("Waiting for API to be ready ...")
    if not wait_for_api(120):
        print("FAILED: API did not start in time")
        stop_api(api_proc)
        return 1
    print("API is ready!")

    print("\nRunning dense eval (label: dense-baseline) ...")
    rc = run_eval("dense-baseline", "dense")
    if rc != 0:
        print(f"Dense eval failed (rc={rc})")
        stop_api(api_proc)
        return rc

    print("\nStopping dense API ...")
    stop_api(api_proc)

    # ── Phase 2: Hybrid ──
    print("\n" + "=" * 60)
    print("  Phase 2: Hybrid RRF eval")
    print("=" * 60)

    print(f"\nStarting API with collection={HYBRID_COLLECTION}, mode=hybrid ...")
    env_hybrid = set_env(HYBRID_COLLECTION, "hybrid")
    api_proc = start_api(env_hybrid)

    print("Waiting for API to be ready ...")
    if not wait_for_api(120):
        print("FAILED: API did not start in time")
        stop_api(api_proc)
        return 1
    print("API is ready!")

    print("\nRunning hybrid eval (label: hybrid-rrf) ...")
    rc = run_eval("hybrid-rrf", "hybrid")
    if rc != 0:
        print(f"Hybrid eval failed (rc={rc})")
        stop_api(api_proc)
        return rc

    print("\nStopping hybrid API ...")
    stop_api(api_proc)

    # ── Phase 3: Compare ──
    print("\n" + "=" * 60)
    print("  Phase 3: Generating A/B comparison (updates LEADERBOARD.md)")
    print("=" * 60)

    result = subprocess.run(
        [
            PYTHON, "scripts/compare_eval_results.py",
            "--label1", "dense-baseline",
            "--label2", "hybrid-rrf",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr, file=sys.stderr)

    # Print the updated leaderboard
    leaderboard = REPO_ROOT / "data" / "eval" / "results" / "LEADERBOARD.md"
    if leaderboard.exists():
        print("\n" + "=" * 60)
        print("  LEADERBOARD.md (updated with A/B comparison)")
        print("=" * 60)
        print(leaderboard.read_text(encoding="utf-8"))

    return 0



if __name__ == "__main__":
    raise SystemExit(main())
