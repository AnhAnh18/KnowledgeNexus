from __future__ import annotations

import hashlib
import importlib.metadata
import socket
from pathlib import Path

from knowledgenexus.foundation.infrastructure.config import load_chunking_profile


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
PROFILE_PATH = REPOSITORY_ROOT / "contracts" / "foundation" / "embedding_profile.yaml"


def _forbid_network(*args: object, **kwargs: object) -> None:
    raise AssertionError("tokenizer asset verification attempted network access")


def test_pinned_tokenizer_assets_verify_and_reload_offline(
    tokenizer_assets_dir: Path, monkeypatch
) -> None:
    profile = load_chunking_profile(PROFILE_PATH)
    for asset in profile.tokenizer_assets:
        path = tokenizer_assets_dir / asset.filename
        assert path.is_file(), f"required tokenizer asset is missing: {asset.filename}"
        body = path.read_bytes()
        assert len(body) == asset.byte_size
        assert hashlib.sha256(body).hexdigest() == asset.sha256

    assert importlib.metadata.version("tokenizers") == profile.tokenizers_version
    monkeypatch.setattr(socket, "socket", _forbid_network)
    monkeypatch.setattr(socket, "create_connection", _forbid_network)

    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(str(tokenizer_assets_dir / "tokenizer.json"))
    samples = (
        "Foundation overview",
        "Kiến thức nền tảng",
        "한국어 테스트",
        "def hello():\n    return 1",
    )
    first = [tokenizer.encode(text, add_special_tokens=False) for text in samples]
    second = [tokenizer.encode(text, add_special_tokens=False) for text in samples]

    expected_ids = [
        [32807, 645, 22751],
        [139238, 7637, 44565, 173947],
        [193751, 153924],
        [8, 420, 33600, 31, 132, 2077, 30646, 106],
    ]
    expected_offsets = [
        [(0, 10), (10, 15), (15, 19)],
        [(0, 4), (4, 9), (9, 13), (13, 18)],
        [(0, 3), (3, 7)],
        [(0, 2), (2, 3), (3, 8), (8, 9), (9, 10), (10, 12), (16, 23), (23, 25)],
    ]
    assert [encoding.ids for encoding in first] == expected_ids
    assert [encoding.offsets for encoding in first] == expected_offsets
    assert [encoding.ids for encoding in second] == expected_ids
    assert [encoding.offsets for encoding in second] == expected_offsets
    assert [len(encoding.ids) for encoding in first] == [
        3,
        4,
        2,
        8,
    ]
    assert all(encoding.ids for encoding in first)
    assert all(
        start <= end <= len(text)
        for text, encoding in zip(samples, first, strict=True)
        for start, end in encoding.offsets
    )
