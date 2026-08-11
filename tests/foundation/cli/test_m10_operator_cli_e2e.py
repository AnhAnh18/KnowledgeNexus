"""Forcing end-to-end tests for the M10 operator CLI.

These drive the subtree harness to a real raw generation plus durable harness
state, then invoke the operator CLI through ``main(argv)`` with a real argument
list. They exist because a CLI that only validates its arguments -- or that
publishes a snapshot with a silently missing stream -- passes every unit test
while being unusable. Each of these caught a defect that unit tests did not:

  * argument wiring: the CLI parsed its arguments and then discarded them;
  * sync state: a CLI stage re-built ``sync_state`` that
    ``AssembleConfluenceM10Handoff`` already owns, so every run failed;
  * Draw.io media: processed assets were pushed through a model that only
    accepts unprocessed media.

No BGE-M3 bundle is required: the tokenizer is injected as a word-splitting
double, so these run offline on any machine.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from knowledgenexus.foundation.cli import confluence_subtree_corpus as cli
from knowledgenexus.foundation.cli import export_m10_snapshot as m10cli
from knowledgenexus.foundation.domain.models import CharacterSpan, TokenizationResult

from tests.foundation.cli.test_confluence_subtree_cli import (
    APPROVED_PROFILE_PATH,
    _FakeHttpInner,
    _FakeInventoryWindowPort,
    _FakeRetryingTransport,
    _args,
    _confluence_page_json,
    _fake_process_result,
    _make_fake_compose_live_subtree,
)

def _contracts_dir() -> Path:
    """Locate contracts/foundation regardless of where this file is placed."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "contracts" / "foundation"
        if candidate.is_dir():
            return candidate
    raise RuntimeError("contracts/foundation not found")


CONTRACTS = _contracts_dir()


class _WordTokenizer:
    def tokenize(self, *, text: str) -> TokenizationResult:
        return TokenizationResult(
            spans=tuple(CharacterSpan(m.start(), m.end()) for m in re.finditer(r"\S+", text))
        )


def _setup(monkeypatch, tmp_path):
    """Drive the harness to a real raw generation plus durable harness state."""
    import knowledgenexus.foundation.infrastructure.confluence as confluence_pkg
    import knowledgenexus.foundation.infrastructure.confluence.confluence_retrying_http_transport as rt

    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://example.invalid/wiki")
    state = (tmp_path / "state").resolve()
    state.mkdir()
    raw_root = (tmp_path / "raw").resolve()
    raw_root.mkdir()
    tok = (tmp_path / "tok").resolve()
    tok.mkdir()

    window_port = _FakeInventoryWindowPort(descendant_page_id="2000", descendant_version="3")
    http_inner = _FakeHttpInner({
        "1000": _confluence_page_json(page_id="1000", title="Root", space_key="SPACE", version=1, html="<p>Root body</p>"),
        "2000": _confluence_page_json(page_id="2000", title="Child", space_key="SPACE", version=3, html="<p>Child body</p>"),
    })
    monkeypatch.setattr(confluence_pkg, "compose_live_subtree", _make_fake_compose_live_subtree(window_port, http_inner))
    monkeypatch.setattr(rt, "RetryingConfluenceHttpTransport", _FakeRetryingTransport)

    base = dict(
        max_pages=10, raw_root=str(raw_root), space_key="SPACE", root_page_id="1000",
        reliability_profile_path=str(APPROVED_PROFILE_PATH),
    )
    cli._inventory_phase(_args(**base), state)
    run_id = cli._inventory_phase(_args(**base, resume_unique=True), state)["run_id"]
    cli._capture_pages_phase(_args(**base, run_id=run_id), state)
    monkeypatch.setattr(cli, "_compose_page_processor", lambda _a, *, run_id, items: _fake_process_result(items))
    cli._process_pages_phase(_args(**base, run_id=run_id), state)

    # The pinned BGE-M3 bundle is not on the review machine; inject a double.
    monkeypatch.setattr(m10cli, "BgeM3LocalTokenizer", lambda **_kw: _WordTokenizer())
    return state, raw_root, tok, run_id


def _argv(*, state, raw_root, tok, run_id, dataset_root, media_policy="disabled"):
    return [
        "--raw-generation-root", str(raw_root), "--state-dir", str(state),
        "--run-id", run_id, "--generation-id", run_id,
        "--chunking-profile", str(CONTRACTS / "embedding_profile.yaml"),
        "--jira-relation-profile", str(CONTRACTS / "jira_relation_profile.yaml"),
        "--tokenizer-assets-dir", str(tok), "--dataset-root", str(dataset_root),
        "--space-key", "SPACE", "--root-page-id", "1000",
        "--git-repository", "knowledgenexus", "--git-branch", "main",
        "--git-commit", "0123456789abcdef0123456789abcdef01234567",
        "--generated-at", "2026-08-11T00:00:00Z", "--media-policy", media_policy,
    ]


def _publish(capsys, argv):
    code = m10cli.main(argv)
    captured = capsys.readouterr()
    assert code == 0, f"CLI did not publish: exit={code} stderr={captured.err.strip()}"
    return json.loads(captured.out.strip().splitlines()[-1])


def test_m10_cli_publishes_from_argv(monkeypatch, tmp_path, capsys):
    """The operator path must publish from a real argument list, not injection."""
    state, raw_root, tok, run_id = _setup(monkeypatch, tmp_path)
    dataset_root = (tmp_path / "dataset").resolve()
    dataset_root.mkdir()

    payload = _publish(capsys, _argv(
        state=state, raw_root=raw_root, tok=tok, run_id=run_id, dataset_root=dataset_root,
    ))

    assert payload["status"] == "success"
    counts = payload["counts"]
    # Page order and identity come from inventory-selection.json.
    assert counts["documents"] == 2 and counts["chunks"] == 2
    # Deny-safe ACL is materialized through the approved producer.
    assert counts["acl"] == 2
    # sync_state is built by AssembleConfluenceM10Handoff, never by a CLI stage.
    assert counts["sync_state"] == 2
    # Confluence-only: pinned Git identity, zero Git rows.
    assert counts["symbols"] == 0


def test_determinism_two_publishes(monkeypatch, tmp_path, capsys):
    state, raw_root, tok, run_id = _setup(monkeypatch, tmp_path)
    payloads = []
    for index in (1, 2):
        dataset_root = (tmp_path / f"dataset{index}").resolve()
        dataset_root.mkdir()
        payloads.append(_publish(capsys, _argv(
            state=state, raw_root=raw_root, tok=tok, run_id=run_id, dataset_root=dataset_root,
        )))
    assert payloads[0]["counts"] == payloads[1]["counts"]
    assert payloads[0]["digest"] == payloads[1]["digest"], "snapshot digest is not deterministic"


def test_drawio_media_path(monkeypatch, tmp_path, capsys):
    """Exercise --media-policy required against real preserved Draw.io evidence."""
    from knowledgenexus.foundation.domain.models.media_body_materialization import (
        MediaAttachmentBodyEnvelope,
        MediaBodyStoreBudget,
    )
    from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_attachment_store import (
        ConfluenceRawAttachmentStore,
    )

    state, raw_root, tok, run_id = _setup(monkeypatch, tmp_path)
    body = (
        b'<mxfile><diagram name="D"><mxGraphModel><root><mxCell id="0"/>'
        b'<mxCell id="2" value="Alpha" vertex="1"/></root></mxGraphModel></diagram></mxfile>'
    )
    attachment_root = raw_root / "attachments"
    attachment_root.mkdir(parents=True, exist_ok=True)
    ConfluenceRawAttachmentStore(
        data_root=attachment_root,
        budget=MediaBodyStoreBudget(256 * 1024 * 1024, 512 * 1024 * 1024, 0),
    ).publish_attachment(envelope=MediaAttachmentBodyEnvelope(
        format_version="1", evidence_kind="confluence_attachment_body",
        attachment_id="att12", parent_page_id="1000", filename="diagram.drawio",
        source_version="3", http_status=200, body_encoding="base64", body_bytes=body,
    ))
    digest = hashlib.sha256(body).hexdigest()

    selection = cli._read_json(cli._state_path(state, run_id, "inventory-selection.json"))
    cli._atomic_json(cli._state_path(state, run_id, "drawio-state.json"), {
        "format_version": "confluence-subtree-drawio-state-v1",
        "run_id": run_id, "generation_id": run_id,
        "selection_identity": selection["selection_identity"],
        "observed": [["1000", "diagram.drawio", "1"]],
        "resolutions": [], "failed": 0,
        "downloaded_bytes": len(body), "artifact_count": 1,
        "media_assets": [{
            "media_id": "m-alpha", "parent_document_id": "confluence:page:1000",
            "filename": "diagram.drawio", "mime_type": "application/xml",
            "size_bytes": len(body), "source_version": "3",
            "raw_uri": f"raw://confluence/attachments/att12/{digest}",
            "content_hash": digest,
        }],
    })

    dataset_root = (tmp_path / "dataset-media").resolve()
    dataset_root.mkdir()
    payload = _publish(capsys, _argv(
        state=state, raw_root=raw_root, tok=tok, run_id=run_id,
        dataset_root=dataset_root, media_policy="required",
    ))

    assert payload["counts"]["media_assets"] >= 1, "Draw.io asset was silently dropped"
