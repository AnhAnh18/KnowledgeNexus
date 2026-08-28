"""Build a read-only inventory diff for an already ingested Confluence root.

This runs the Foundation *inventory* phase only.  Inventory lists the subtree
and records each page's ``source_version``; it never fetches page bodies and
never touches the index, so an operator can ask "what would a sync do?" on a
5k-page root without paying for a crawl or risking the demo index.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
from threading import Lock
from typing import Any

from knowledgenexus.foundation.cli import confluence_subtree_corpus
from knowledgenexus.foundation.cli.export_confluence_url_text_snapshot import (
    parse_canonical_page_url,
)
from knowledgenexus.indexing.application.use_cases.confluence_sync_state import (
    PageState,
    RootIdentity,
    build_sync_plan,
    find_baseline_workspace,
    read_packet_pages,
)

# The Foundation phase entry point reads credentials from the process
# environment, so only one caller may publish them at a time.
_ENV_LOCK = Lock()

# How many page ids each list in the response carries. The counts are always
# exact; the id lists exist so an operator can eyeball a sample, and a 5k-page
# root must not turn one job-status row into a megabyte of JSON.
_MAX_LISTED_IDS = 200


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _live_inventory(
    *, base_url: str, space_key: str, root_page_id: str, workspace: Path, max_pages: int,
    reliability_profile: Path, tokenizer_assets_dir: Path | None, confluence_pat: str | None,
) -> dict[str, Any]:
    """Run the inventory phase and return its published selection payload."""
    state, raw = workspace / ".state", workspace / ".raw"
    state.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    argv = [
        "inventory",
        "--state-dir", str(state), "--max-pages", str(max_pages),
        "--raw-root", str(raw), "--reliability-profile-path", str(reliability_profile),
        "--space-key", space_key, "--root-page-id", root_page_id,
    ]
    if tokenizer_assets_dir is not None:
        argv.extend(("--tokenizer-assets-dir", str(tokenizer_assets_dir)))
    out = io.StringIO()
    err = io.StringIO()
    with _ENV_LOCK:
        prior_pat = os.environ.get("CONFLUENCE_PAT")
        prior_base = os.environ.get("CONFLUENCE_BASE_URL")
        os.environ["CONFLUENCE_BASE_URL"] = base_url
        if confluence_pat:
            os.environ["CONFLUENCE_PAT"] = confluence_pat
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                if confluence_subtree_corpus.main(argv) != 0:
                    raise RuntimeError("inventory_failed")
        finally:
            for name, prior in (("CONFLUENCE_PAT", prior_pat), ("CONFLUENCE_BASE_URL", prior_base)):
                if prior is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = prior
    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("inventory_no_result")
    inventory = json.loads(lines[-1])
    run_id, selected = inventory.get("run_id"), inventory.get("selected_pages")
    if (
        inventory.get("status") != "complete"
        or type(run_id) is not str or type(selected) is not int
    ):
        raise RuntimeError("inventory_invalid_result")
    payload = _read_json(state / "runs" / run_id / "inventory-selection.json")
    payload["run_id"] = run_id
    payload["selected_pages"] = selected
    return payload


def _selection_pages(payload: dict[str, Any]) -> dict[str, PageState]:
    pages: dict[str, PageState] = {}
    for row in payload.get("items", []):
        if type(row) is not dict:
            continue
        page_id, version = row.get("page_id"), row.get("expected_source_version")
        if type(page_id) is not str or not page_id or type(version) is not str or not version:
            continue
        pages[page_id] = PageState(f"confluence:page:{page_id}", page_id, version)
    return pages


def preview_sync(
    *, url: str, workspace: Path, snapshot_root: Path, max_pages: int,
    reliability_profile: Path, tokenizer_assets_dir: Path | None,
    previous_workspace: Path | None = None, confluence_pat: str | None = None,
) -> dict[str, Any]:
    """Inventory a root live and diff it against the last published packet.

    ``previous_workspace`` pins the baseline explicitly; when it is omitted the
    snapshot root is scanned for the most recent workspace published for the
    same ``(base_url, space_key, root_page_id)``.  With no baseline at all the
    result is reported as ``baseline_required`` rather than pretending every
    page is new -- an apply run from that state would be a first full ingest,
    which is a different decision for the operator to make.
    """
    base_url, space_key, root_page_id = parse_canonical_page_url(url)
    identity = RootIdentity(base_url, space_key, root_page_id)
    payload = _live_inventory(
        base_url=base_url, space_key=space_key, root_page_id=root_page_id,
        workspace=workspace, max_pages=max_pages, reliability_profile=reliability_profile,
        tokenizer_assets_dir=tokenizer_assets_dir, confluence_pat=confluence_pat,
    )
    current = _selection_pages(payload)
    baseline_workspace = previous_workspace
    if baseline_workspace is None:
        baseline_workspace = find_baseline_workspace(
            snapshot_root=snapshot_root, identity=identity,
            exclude=frozenset({workspace.name}),
        )
    baseline = read_packet_pages(baseline_workspace) if baseline_workspace else {}
    plan = build_sync_plan(baseline=baseline, current=current)
    return {
        "status": "complete" if baseline else "baseline_required",
        "phase": "sync_preview",
        "run_id": payload["run_id"],
        "space_key": space_key,
        "root_page_id": root_page_id,
        "canonical_url": identity.canonical_url,
        "selected_pages": payload["selected_pages"],
        "selection_identity": payload.get("selection_identity"),
        **plan.counts(),
        "new_page_ids": list(plan.new_page_ids[:_MAX_LISTED_IDS]),
        "changed_page_ids": list(plan.changed_page_ids[:_MAX_LISTED_IDS]),
        "deleted_page_ids": list(plan.deleted_page_ids[:_MAX_LISTED_IDS]),
        "baseline_found": bool(baseline),
        "baseline_workspace": str(baseline_workspace) if baseline_workspace else None,
        "baseline_pages": len(baseline),
        "inventory_workspace": str(workspace),
    }
