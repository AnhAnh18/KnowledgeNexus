"""Operator wrapper for a deny-safe, versioned Confluence text packet.

The wrapper deliberately composes the already approved subtree phases.  It
does not weaken M10 full-snapshot ACL invariants and it never turns unresolved
Confluence permissions into public access.  Published chunks therefore retain
``restricted:unresolved`` until a later ACL-aware pipeline replaces them.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import parse_qsl, unquote, urlsplit

from knowledgenexus.foundation.ports.path_safety import (
    require_plain_directory_chain,
    require_plain_file,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_CHUNKING_PROFILE = _REPOSITORY_ROOT / "contracts" / "foundation" / "embedding_profile.yaml"
_DEFAULT_RELIABILITY_PROFILE = _REPOSITORY_ROOT / "contracts" / "foundation" / "crawl_reliability_profile.yaml"
_CONTEXT_FILE = "text-snapshot-context.json"
_CONTEXT_FORMAT = "confluence-url-text-snapshot-context-v1"
_PACKET_FILES = frozenset(
    {"documents.jsonl", "chunks.jsonl", "media_assets.jsonl", "packet_summary.json"}
)
_CANONICAL_PAGE_PATH = re.compile(
    r"\A(?P<context>(?:/[^/?#]+)*)/spaces/(?P<space>[A-Z0-9]+)/pages/(?P<page>[0-9]+)(?:/[^?#]*)?\Z"
)
_VIEW_PAGE_PATH = re.compile(
    r"\A(?P<context>(?:/[^/?#]+)*)/pages/viewpage\.action\Z",
    re.IGNORECASE,
)
_VIEW_PAGE_QUERY_FIELDS = frozenset({"pageId", "spaceKey", "title"})
_SHORT_PAGE_PATH = re.compile(
    r"\A(?P<context>(?:/[^/?#]+)*)/x/(?P<token>[A-Za-z0-9_-]{1,11})\Z"
)
_RUN_ID = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)


class TextSnapshotOperatorError(Exception):
    """Sanitized operator failure; the message is intentionally unused."""

    def __init__(self, category: str) -> None:
        super().__init__()
        self.category = category


def _decode_short_page_id(token: str) -> str:
    try:
        padding = "=" * ((4 - len(token) % 4) % 4)
        raw = base64.b64decode(token + padding, altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        raise TextSnapshotOperatorError("url") from None
    if not raw or len(raw) > 8:
        raise TextSnapshotOperatorError("url")
    page_number = int.from_bytes(raw, byteorder="little", signed=False)
    if page_number <= 0:
        raise TextSnapshotOperatorError("url")
    minimal = page_number.to_bytes((page_number.bit_length() + 7) // 8, "little")
    canonical = base64.urlsafe_b64encode(minimal).rstrip(b"=").decode("ascii")
    if canonical != token:
        raise TextSnapshotOperatorError("url")
    return str(page_number)


def parse_canonical_page_url(
    value: object, *,
    short_space_resolver: Callable[[str, str], object] | None = None,
) -> tuple[str, str, str]:
    """Return ``(base_url, space_key, page_id)`` from a canonical page URL."""

    if type(value) is not str or not value or any(char.isspace() for char in value):
        raise TextSnapshotOperatorError("url")
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise TextSnapshotOperatorError("url") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise TextSnapshotOperatorError("url")
    try:
        port = parsed.port
    except ValueError:
        raise TextSnapshotOperatorError("url") from None
    decoded_path = unquote(parsed.path)
    host = parsed.hostname.lower()
    authority = f"{host}:{port}" if port is not None and port != 443 else host
    match = _CANONICAL_PAGE_PATH.fullmatch(decoded_path)
    if match is not None:
        if parsed.query:
            raise TextSnapshotOperatorError("url")
        context = match.group("context").rstrip("/")
        space_key, page_id = match.group("space"), match.group("page")
    else:
        view_match = _VIEW_PAGE_PATH.fullmatch(decoded_path)
        short_match = _SHORT_PAGE_PATH.fullmatch(decoded_path)
        if short_match is not None:
            if parsed.query or short_space_resolver is None:
                raise TextSnapshotOperatorError("url_requires_resolution")
            page_id = _decode_short_page_id(short_match.group("token"))
            context = short_match.group("context").rstrip("/")
            base_url = f"https://{authority}{context}"
            try:
                space_key = short_space_resolver(base_url, page_id)
            except TextSnapshotOperatorError:
                raise
            except Exception:
                raise TextSnapshotOperatorError("short_url_resolution") from None
            if type(space_key) is not str or re.fullmatch(r"[A-Z0-9]+", space_key) is None:
                raise TextSnapshotOperatorError("short_url_resolution")
            return base_url, space_key, page_id
        if view_match is None or not parsed.query:
            raise TextSnapshotOperatorError("url_shape")
        try:
            pairs = parse_qsl(
                parsed.query, keep_blank_values=True, strict_parsing=True,
                encoding="utf-8", errors="strict",
            )
        except (UnicodeDecodeError, ValueError):
            raise TextSnapshotOperatorError("url") from None
        query: dict[str, str] = {}
        for key, item in pairs:
            if key in query or key not in _VIEW_PAGE_QUERY_FIELDS:
                raise TextSnapshotOperatorError("url")
            query[key] = item
        if set(query) not in ({"pageId", "spaceKey"}, _VIEW_PAGE_QUERY_FIELDS):
            raise TextSnapshotOperatorError("url")
        page_id, space_key = query["pageId"], query["spaceKey"]
        if (
            not page_id
            or not page_id.isascii()
            or not page_id.isdecimal()
            or re.fullmatch(r"[A-Z0-9]+", space_key) is None
            or ("title" in query and not query["title"])
        ):
            raise TextSnapshotOperatorError("url")
        context = view_match.group("context").rstrip("/")
    return f"https://{authority}{context}", space_key, page_id


def _resolve_short_space_key(base_url: str, page_id: str) -> str:
    try:
        from knowledgenexus.foundation.cli.confluence_subtree_corpus import (
            _load_reliability_profile,
        )
        from knowledgenexus.foundation.infrastructure.confluence.confluence_http_transport import (
            UrllibConfluenceHttpTransport,
        )
        from knowledgenexus.foundation.infrastructure.confluence.confluence_retrying_http_transport import (
            ConfluenceRetryExecutorProfile,
            RetryingConfluenceHttpTransport,
        )

        profile_mapping = _load_reliability_profile(str(_DEFAULT_RELIABILITY_PROFILE))
        profile = ConfluenceRetryExecutorProfile.from_mapping(profile_mapping)
        inner = UrllibConfluenceHttpTransport(
            base_url=base_url,
            personal_access_token=os.environ.get("CONFLUENCE_PAT"),
            max_response_bytes=profile_mapping["max_response_bytes_per_request"],
        )
        transport = RetryingConfluenceHttpTransport(
            inner=inner, profile=profile,
            monotonic_clock=time.monotonic, sleeper=time.sleep,
        )
        payload = transport.get_json(
            path=f"/rest/api/content/{page_id}", query={"expand": "space"},
        )
    except Exception:
        raise TextSnapshotOperatorError("short_url_resolution") from None
    space = payload.get("space") if type(payload) is dict else None
    key = space.get("key") if type(space) is dict else None
    if (
        payload.get("id") != page_id
        or payload.get("type") != "page"
        or type(key) is not str
        or re.fullmatch(r"[A-Z0-9]+", key) is None
    ):
        raise TextSnapshotOperatorError("short_url_resolution")
    return key


def _canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            dict(payload), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _atomic_write(path: Path, payload: bytes, *, replace: bool) -> None:
    require_plain_directory_chain(path.parent)
    temporary = path.parent / f".{path.name}.tmp"
    if temporary.exists():
        raise TextSnapshotOperatorError("publication")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
            temporary.unlink()
    except TextSnapshotOperatorError:
        raise
    except (OSError, ValueError):
        raise TextSnapshotOperatorError("publication") from None
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _safe_root(value: object) -> Path:
    if type(value) is not str:
        raise TextSnapshotOperatorError("output")
    root = Path(value)
    if not root.is_absolute() or root == Path(root.anchor):
        raise TextSnapshotOperatorError("output")
    resolved = root.resolve(strict=False)
    repository = _REPOSITORY_ROOT.resolve()
    try:
        resolved.relative_to(repository)
    except ValueError:
        pass
    else:
        raise TextSnapshotOperatorError("output")
    if root.exists():
        require_plain_directory_chain(root)
    else:
        require_plain_directory_chain(root.parent)
        try:
            root.mkdir()
        except OSError:
            raise TextSnapshotOperatorError("output") from None
        require_plain_directory_chain(root)
    return root


def _require_operator_inputs(tokenizer_value: object) -> Path:
    if type(os.environ.get("CONFLUENCE_PAT")) is not str or not os.environ["CONFLUENCE_PAT"]:
        raise TextSnapshotOperatorError("credentials")
    if type(tokenizer_value) is not str or not tokenizer_value:
        raise TextSnapshotOperatorError("tokenizer")
    tokenizer = Path(tokenizer_value)
    if not tokenizer.is_absolute():
        raise TextSnapshotOperatorError("tokenizer")
    try:
        require_plain_directory_chain(tokenizer)
        require_plain_file(tokenizer / "tokenizer.json")
        require_plain_file(_DEFAULT_CHUNKING_PROFILE)
        require_plain_file(_DEFAULT_RELIABILITY_PROFILE)
    except Exception:
        raise TextSnapshotOperatorError("tokenizer") from None
    return tokenizer


def _load_context(path: Path, expected: Mapping[str, object]) -> dict[str, object]:
    if not path.exists():
        payload = dict(expected)
        payload.update({"format_version": _CONTEXT_FORMAT, "inventory_started": False, "run_id": None})
        _atomic_write(path, _canonical_json_bytes(payload), replace=False)
        return payload
    try:
        require_plain_file(path)
        if path.stat().st_size > 16 * 1024:
            raise ValueError
        payload = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise TextSnapshotOperatorError("context") from None
    fields = set(expected) | {"format_version", "inventory_started", "run_id"}
    if type(payload) is not dict or set(payload) != fields:
        raise TextSnapshotOperatorError("context")
    if payload.get("format_version") != _CONTEXT_FORMAT:
        raise TextSnapshotOperatorError("context")
    if any(payload.get(key) != value for key, value in expected.items()):
        raise TextSnapshotOperatorError("context_binding")
    if type(payload.get("inventory_started")) is not bool:
        raise TextSnapshotOperatorError("context")
    run_id = payload.get("run_id")
    if run_id is not None and (type(run_id) is not str or _RUN_ID.fullmatch(run_id) is None):
        raise TextSnapshotOperatorError("context")
    return dict(payload)


def _save_context(path: Path, payload: Mapping[str, object]) -> None:
    _atomic_write(path, _canonical_json_bytes(payload), replace=True)


def _invoke_phase(
    argv: list[str], *, phase_main: Callable[[list[str] | None], int]
) -> dict[str, object]:
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            exit_code = phase_main(argv)
    except Exception:
        raise TextSnapshotOperatorError("phase") from None
    lines = output.getvalue().splitlines()
    if type(exit_code) is not int or len(lines) != 1:
        raise TextSnapshotOperatorError("phase")
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError:
        raise TextSnapshotOperatorError("phase") from None
    if type(payload) is not dict or type(payload.get("status")) is not str:
        raise TextSnapshotOperatorError("phase")
    if exit_code != 0 or payload["status"] == "failed":
        category = payload.get("failure_category")
        raise TextSnapshotOperatorError(category if type(category) is str and category else "phase")
    return dict(payload)


def _require_phase_result(
    payload: object, *, phase: str, statuses: frozenset[str],
    counters: tuple[str, ...] = (), booleans: tuple[str, ...] = (),
) -> dict[str, object]:
    if type(payload) is not dict or payload.get("phase") != phase:
        raise TextSnapshotOperatorError(phase)
    status = payload.get("status")
    if type(status) is not str or status not in statuses:
        raise TextSnapshotOperatorError(phase)
    for name in counters:
        value = payload.get(name)
        if type(value) is not int or value < 0:
            raise TextSnapshotOperatorError(phase)
    for name in booleans:
        if type(payload.get(name)) is not bool:
            raise TextSnapshotOperatorError(phase)
    return dict(payload)


def _common_phase_args(
    *, state: Path, raw: Path, reliability: Path, max_pages: int,
    space_key: str, root_page_id: str,
) -> list[str]:
    return [
        "--state-dir", str(state), "--raw-root", str(raw),
        "--reliability-profile-path", str(reliability),
        "--max-pages", str(max_pages), "--batch-size", "100",
        "--space-key", space_key, "--root-page-id", root_page_id,
    ]


def _verify_existing_packet(version: Path) -> None:
    try:
        require_plain_directory_chain(version)
        names = {item.name for item in version.iterdir()}
        if names != _PACKET_FILES:
            raise ValueError
        for name in _PACKET_FILES:
            require_plain_file(version / name)
        summary = json.loads((version / "packet_summary.json").read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise TextSnapshotOperatorError("publication") from None
    if (
        type(summary) is not dict
        or summary.get("format_version") != "confluence-subtree-indexing-packet-v1"
        or summary.get("acl_mode") != "restricted_unresolved"
        or type(summary.get("document_count")) is not int
        or summary["document_count"] <= 0
        or type(summary.get("chunk_count")) is not int
        or summary["chunk_count"] <= 0
    ):
        raise TextSnapshotOperatorError("publication")


def run(
    *, url: object, output_root: object, tokenizer_assets_dir: object,
    max_pages: object = 5_000,
    phase_main: Callable[[list[str] | None], int] | None = None,
    short_space_resolver: Callable[[str, str], object] | None = None,
) -> dict[str, object]:
    if type(max_pages) is not int or max_pages <= 0 or max_pages > 5_000:
        raise TextSnapshotOperatorError("page_bound")
    tokenizer = _require_operator_inputs(tokenizer_assets_dir)
    resolver = _resolve_short_space_key if short_space_resolver is None else short_space_resolver
    base_url, space_key, root_page_id = parse_canonical_page_url(
        url, short_space_resolver=resolver,
    )
    root = _safe_root(output_root)
    state, raw, versions = root / ".state", root / ".raw", root / "versions"
    context_path = root / _CONTEXT_FILE
    if not context_path.exists() and any(root.iterdir()):
        raise TextSnapshotOperatorError("output_not_empty")
    context = _load_context(context_path, expected={
        "base_url": base_url, "space_key": space_key,
        "root_page_id": root_page_id, "max_pages": max_pages,
    })
    for directory in (state, raw, versions):
        if directory.exists():
            require_plain_directory_chain(directory)
        else:
            directory.mkdir()
            require_plain_directory_chain(directory)

    os.environ["CONFLUENCE_BASE_URL"] = base_url
    if phase_main is None:
        from knowledgenexus.foundation.cli.confluence_subtree_corpus import main as phase_main

    common = _common_phase_args(
        state=state, raw=raw, reliability=_DEFAULT_RELIABILITY_PROFILE,
        max_pages=max_pages, space_key=space_key, root_page_id=root_page_id,
    )
    run_id = context["run_id"]
    if run_id is None:
        inventory_args = ["inventory", *common]
        if context["inventory_started"]:
            inventory_args.append("--resume-unique")
        else:
            context["inventory_started"] = True
            _save_context(context_path, context)
        inventory = _require_phase_result(
            _invoke_phase(inventory_args, phase_main=phase_main),
            phase="inventory", statuses=frozenset({"complete", "completed"}),
            counters=("selected_pages",),
        )
        # The durable inventory use case intentionally returns the activation
        # snapshot captured before its final commit.  A newly completed crawl
        # therefore reports ``completed`` with zero selected pages; one
        # bounded resume observes the committed COMPLETE snapshot and
        # publishes the immutable selection.  This is a read-after-commit
        # handoff, not a second crawl.
        if inventory["status"] == "completed":
            if inventory["selected_pages"] != 0:
                raise TextSnapshotOperatorError("inventory")
            inventory = _require_phase_result(
                _invoke_phase(
                    ["inventory", *common, "--resume-unique"],
                    phase_main=phase_main,
                ),
                phase="inventory", statuses=frozenset({"complete"}),
                counters=("selected_pages",),
            )
        if inventory["status"] != "complete" or inventory["selected_pages"] <= 0:
            raise TextSnapshotOperatorError("inventory")
        run_id = inventory.get("run_id")
        if type(run_id) is not str or _RUN_ID.fullmatch(run_id) is None:
            raise TextSnapshotOperatorError("inventory")
        context["run_id"] = run_id
        _save_context(context_path, context)

    version_name = f"confluence-{run_id}"
    version = versions / version_name
    latest = root / "LATEST.txt"
    if version.exists():
        _verify_existing_packet(version)
        if latest.exists():
            require_plain_file(latest)
            if latest.read_bytes() != (version_name + "\n").encode("ascii"):
                raise TextSnapshotOperatorError("publication")
        else:
            _atomic_write(latest, (version_name + "\n").encode("ascii"), replace=False)
        return {"status": "complete", "already_published": True, "acl_mode": "restricted_unresolved"}

    capture_args = ["capture-pages", *common, "--run-id", run_id, "--stop-after-batches", "1"]
    maximum_batches = (max_pages + 99) // 100
    for _ in range(maximum_batches):
        captured = _require_phase_result(
            _invoke_phase(capture_args, phase_main=phase_main),
            phase="capture-pages", statuses=frozenset({"complete", "stopped"}),
            counters=("captured", "replayed", "skipped", "failed"),
        )
        if captured["status"] == "complete":
            break
        if captured["status"] != "stopped":
            raise TextSnapshotOperatorError("capture")
        failed = captured["failed"]
        if failed:
            raise TextSnapshotOperatorError("capture_incomplete")
    else:
        raise TextSnapshotOperatorError("capture_incomplete")

    processing = [
        "process-pages", *common, "--run-id", run_id,
        "--chunking-profile-path", str(_DEFAULT_CHUNKING_PROFILE),
        "--tokenizer-assets-dir", str(tokenizer),
    ]
    _require_phase_result(
        _invoke_phase(processing, phase_main=phase_main),
        phase="process-pages", statuses=frozenset({"complete"}),
    )
    _require_phase_result(
        _invoke_phase(["capture-drawio", *common, "--run-id", run_id], phase_main=phase_main),
        phase="capture-drawio", statuses=frozenset({"complete"}),
    )
    exported = _require_phase_result(_invoke_phase(
        [
            "export", *common, "--run-id", run_id,
            "--chunking-profile-path", str(_DEFAULT_CHUNKING_PROFILE),
            "--tokenizer-assets-dir", str(tokenizer),
            "--output-dir", str(version),
        ],
        phase_main=phase_main,
    ), phase="export", statuses=frozenset({"complete"}),
        counters=("document_count", "chunk_count", "media_asset_count"),
        booleans=("packet_published",),
    )
    if exported["packet_published"] is not True:
        raise TextSnapshotOperatorError("publication")
    _verify_existing_packet(version)
    _atomic_write(latest, (version_name + "\n").encode("ascii"), replace=False)
    return {
        "status": "complete", "already_published": False,
        "document_count": exported.get("document_count"),
        "chunk_count": exported.get("chunk_count"),
        "media_asset_count": exported.get("media_asset_count"),
        "acl_mode": "restricted_unresolved",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="export-confluence-url-text-snapshot")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--max-pages", type=int, default=5_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        result = run(
            url=args.url, output_root=args.output_root,
            tokenizer_assets_dir=os.environ.get("KN_TOKENIZER_ASSETS_DIR"),
            max_pages=args.max_pages,
        )
        sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    except SystemExit as exc:
        return int(exc.code)
    except TextSnapshotOperatorError as exc:
        sys.stderr.write(json.dumps({"status": "failed", "category": exc.category}, sort_keys=True, separators=(",", ":")) + "\n")
        return 1
    except Exception:
        sys.stderr.write('{"category":"unexpected","status":"failed"}\n')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
