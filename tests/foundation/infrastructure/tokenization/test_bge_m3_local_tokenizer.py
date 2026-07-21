from __future__ import annotations

import hashlib
import socket
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from knowledgenexus.foundation.domain.models import (
    CharacterSpan,
    ChunkingProfile,
    TokenizerAsset,
)
from knowledgenexus.foundation.infrastructure.config import load_chunking_profile
from knowledgenexus.foundation.infrastructure.tokenization import BgeM3LocalTokenizer
from knowledgenexus.foundation.infrastructure.tokenization import (
    bge_m3_local_tokenizer as adapter_module,
)
from knowledgenexus.foundation.ports import (
    TokenizerError,
    TokenizerFailureCategory,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
PROFILE_PATH = REPOSITORY_ROOT / "contracts" / "foundation" / "embedding_profile.yaml"


class _FakeTokenizer:
    def __init__(
        self,
        *,
        offsets: list[tuple[int, int]] | None = None,
        ids: list[int] | None = None,
        truncation: object | None = None,
        padding: object | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.truncation = truncation
        self.padding = padding
        self._offsets = offsets if offsets is not None else [(0, 1)]
        self._ids = ids if ids is not None else list(range(len(self._offsets)))
        self._failure = failure
        self.add_special_tokens_arguments: list[bool] = []
        self.sequences: list[str] = []

    def encode(self, sequence: str, add_special_tokens: bool = True):
        self.sequences.append(sequence)
        self.add_special_tokens_arguments.append(add_special_tokens)
        if self._failure is not None:
            raise self._failure
        return SimpleNamespace(offsets=self._offsets, ids=self._ids)


def _profile() -> ChunkingProfile:
    return load_chunking_profile(PROFILE_PATH)


def _profile_for_body(profile: ChunkingProfile, body: bytes) -> ChunkingProfile:
    return replace(
        profile,
        tokenizer_assets=(
            TokenizerAsset(
                filename="tokenizer.json",
                byte_size=len(body),
                sha256=hashlib.sha256(body).hexdigest(),
            ),
        ),
    )


def _write_asset(tmp_path: Path, body: bytes) -> Path:
    path = tmp_path / "tokenizer.json"
    path.write_bytes(body)
    return path


def _adapter_with_fake(tokenizer: _FakeTokenizer) -> BgeM3LocalTokenizer:
    adapter = object.__new__(BgeM3LocalTokenizer)
    adapter._tokenizer = tokenizer
    return adapter


def _assert_category(
    captured: pytest.ExceptionInfo[TokenizerError],
    category: TokenizerFailureCategory,
) -> None:
    assert captured.value.category is category
    assert str(captured.value) == category.value
    assert captured.value.__cause__ is None


def _forbid_network(*args: object, **kwargs: object) -> None:
    raise AssertionError("tokenizer attempted network access")


def test_approved_bundle_loads_and_matches_direct_pinned_reference(
    tokenizer_assets_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "socket", _forbid_network)
    monkeypatch.setattr(socket, "create_connection", _forbid_network)
    profile = _profile()
    adapter = BgeM3LocalTokenizer(
        profile=profile,
        tokenizer_assets_dir=tokenizer_assets_dir,
    )

    from tokenizers import Tokenizer

    body = (tokenizer_assets_dir / "tokenizer.json").read_bytes()
    reference = Tokenizer.from_str(body.decode("utf-8"))
    assert reference.truncation is None
    assert reference.padding is None

    samples = (
        "",
        "Foundation overview",
        "Kiến thức nền tảng",
        "한국어 테스트",
        "English và 한국어",
        "def hello():\n    return 1",
        "## Heading\n\n- first\n- second",
        "👩🏽‍💻 test",
        "a\u0338",
    )
    for text in samples:
        result = adapter.tokenize(text=text)
        expected = reference.encode(text, add_special_tokens=False)
        assert result.token_count == len(expected.ids)
        assert [(span.start, span.end) for span in result.spans] == expected.offsets
        assert adapter.tokenize(text=text) == result

    without_special = reference.encode("Foundation", add_special_tokens=False)
    with_special = reference.encode("Foundation", add_special_tokens=True)
    assert adapter.tokenize(text="Foundation").token_count == len(without_special.ids)
    assert len(with_special.ids) > len(without_special.ids)

    long_text = "hello " * 9_000
    long_result = adapter.tokenize(text=long_text)
    expected_long = reference.encode(long_text, add_special_tokens=False)
    assert long_result.token_count == len(expected_long.ids)
    assert long_result.token_count > profile.maximum_model_tokens
    assert long_result.spans[-1].end <= len(long_text)


def test_missing_size_and_hash_mismatches_fail_closed(tmp_path: Path) -> None:
    profile = _profile()
    with pytest.raises(TokenizerError) as missing:
        BgeM3LocalTokenizer(profile=profile, tokenizer_assets_dir=tmp_path)
    _assert_category(missing, TokenizerFailureCategory.ASSETS_MISSING)

    _write_asset(tmp_path, b"x")
    with pytest.raises(TokenizerError) as wrong_size:
        BgeM3LocalTokenizer(profile=profile, tokenizer_assets_dir=tmp_path)
    _assert_category(wrong_size, TokenizerFailureCategory.ASSET_SIZE_MISMATCH)

    body = b"{}"
    _write_asset(tmp_path, body)
    wrong_hash_profile = replace(
        _profile_for_body(profile, body),
        tokenizer_assets=(
            TokenizerAsset(
                filename="tokenizer.json",
                byte_size=len(body),
                sha256=hashlib.sha256(b"[]").hexdigest(),
            ),
        ),
    )
    with pytest.raises(TokenizerError) as wrong_hash:
        BgeM3LocalTokenizer(
            profile=wrong_hash_profile,
            tokenizer_assets_dir=tmp_path,
        )
    _assert_category(wrong_hash, TokenizerFailureCategory.ASSET_HASH_MISMATCH)


def test_decode_and_tokenizer_json_failures_are_categorized(tmp_path: Path) -> None:
    invalid_utf8 = b"\xff"
    _write_asset(tmp_path, invalid_utf8)
    with pytest.raises(TokenizerError) as decode_failed:
        BgeM3LocalTokenizer(
            profile=_profile_for_body(_profile(), invalid_utf8),
            tokenizer_assets_dir=tmp_path,
        )
    _assert_category(decode_failed, TokenizerFailureCategory.ASSET_DECODE_FAILED)

    invalid_json = b"not tokenizer json"
    _write_asset(tmp_path, invalid_json)
    with pytest.raises(TokenizerError) as load_failed:
        BgeM3LocalTokenizer(
            profile=_profile_for_body(_profile(), invalid_json),
            tokenizer_assets_dir=tmp_path,
        )
    _assert_category(load_failed, TokenizerFailureCategory.LOAD_FAILED)


def test_verified_bytes_are_read_once_and_are_the_bytes_loaded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_body = b'{"verified":"original"}'
    asset_path = _write_asset(tmp_path, original_body)
    profile = _profile_for_body(_profile(), original_body)
    original_read_bytes = Path.read_bytes
    reads: list[Path] = []
    loaded: list[str] = []

    def recording_read_bytes(path: Path) -> bytes:
        if path == asset_path:
            reads.append(path)
        return original_read_bytes(path)

    def replacing_loader(serialized: str) -> _FakeTokenizer:
        loaded.append(serialized)
        asset_path.write_bytes(b'{"replacement":true}')
        return _FakeTokenizer()

    monkeypatch.setattr(Path, "read_bytes", recording_read_bytes)
    monkeypatch.setattr(adapter_module, "_tokenizer_from_str", replacing_loader)

    BgeM3LocalTokenizer(profile=profile, tokenizer_assets_dir=tmp_path)

    assert reads == [asset_path]
    assert loaded == [original_body.decode("utf-8")]
    assert asset_path.read_bytes() != original_body


@pytest.mark.parametrize(
    ("truncation", "padding"),
    [({"max_length": 1}, None), (None, {"length": 1})],
)
def test_truncation_or_padding_configuration_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    truncation: object | None,
    padding: object | None,
) -> None:
    body = b'{"fixture":true}'
    _write_asset(tmp_path, body)
    monkeypatch.setattr(
        adapter_module,
        "_tokenizer_from_str",
        lambda serialized: _FakeTokenizer(truncation=truncation, padding=padding),
    )

    with pytest.raises(TokenizerError) as captured:
        BgeM3LocalTokenizer(
            profile=_profile_for_body(_profile(), body),
            tokenizer_assets_dir=tmp_path,
        )
    _assert_category(captured, TokenizerFailureCategory.CONFIGURATION_INVALID)


def test_runtime_tokenizers_version_must_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter_module.metadata, "version", lambda name: "0.0.0")

    with pytest.raises(TokenizerError) as captured:
        BgeM3LocalTokenizer(profile=_profile(), tokenizer_assets_dir=tmp_path)
    _assert_category(captured, TokenizerFailureCategory.RUNTIME_VERSION_MISMATCH)


def test_non_nfc_input_fails_without_being_normalized() -> None:
    adapter = _adapter_with_fake(_FakeTokenizer())

    with pytest.raises(TokenizerError) as captured:
        adapter.tokenize(text="e\u0301")
    _assert_category(captured, TokenizerFailureCategory.OFFSET_INVALID)


def test_overlapping_and_equal_offsets_are_valid_and_special_tokens_are_disabled() -> None:
    tokenizer = _FakeTokenizer(offsets=[(0, 1), (0, 1), (1, 2)])
    adapter = _adapter_with_fake(tokenizer)

    result = adapter.tokenize(text="ab")

    assert result.spans == (
        CharacterSpan(0, 1),
        CharacterSpan(0, 1),
        CharacterSpan(1, 2),
    )
    assert tokenizer.add_special_tokens_arguments == [False]
    assert tokenizer.sequences == ["ab"]


def test_adapter_passes_nfc_input_to_tokenizer_without_modification() -> None:
    text = "Kiến thức a\u0338"
    tokenizer = _FakeTokenizer(offsets=[(0, len(text))])
    adapter = _adapter_with_fake(tokenizer)

    adapter.tokenize(text=text)

    assert tokenizer.sequences == [text]


@pytest.mark.parametrize(
    ("text", "offsets", "ids"),
    [
        ("a", [(0, 0)], [1]),
        ("a", [(0, 2)], [1]),
        ("abc", [(1, 2), (0, 3)], [1, 2]),
        ("abc", [(0, 3), (1, 2)], [1, 2]),
        ("a", [(0, 1)], [1, 2]),
    ],
)
def test_invalid_offsets_fail_closed(
    text: str,
    offsets: list[tuple[int, int]],
    ids: list[int],
) -> None:
    adapter = _adapter_with_fake(_FakeTokenizer(offsets=offsets, ids=ids))

    with pytest.raises(TokenizerError) as captured:
        adapter.tokenize(text=text)
    _assert_category(captured, TokenizerFailureCategory.OFFSET_INVALID)


def test_tokenization_failure_does_not_disclose_source_or_cause() -> None:
    marker = "confidential-source-marker"
    adapter = _adapter_with_fake(
        _FakeTokenizer(failure=RuntimeError(f"failed on {marker}"))
    )

    with pytest.raises(TokenizerError) as captured:
        adapter.tokenize(text=marker)

    _assert_category(captured, TokenizerFailureCategory.TOKENIZATION_FAILED)
    assert marker not in str(captured.value)


def test_asset_failure_does_not_disclose_path_or_hash(tmp_path: Path) -> None:
    marker = "private-user-and-host-marker"
    missing_directory = tmp_path / marker
    profile = _profile()

    with pytest.raises(TokenizerError) as captured:
        BgeM3LocalTokenizer(
            profile=profile,
            tokenizer_assets_dir=missing_directory,
        )

    _assert_category(captured, TokenizerFailureCategory.ASSETS_MISSING)
    message = str(captured.value)
    assert marker not in message
    assert str(missing_directory) not in message
    assert profile.tokenizer_assets[0].sha256 not in message


def test_input_and_constructor_types_fail_safely(tmp_path: Path) -> None:
    adapter = _adapter_with_fake(_FakeTokenizer())
    with pytest.raises(TypeError, match="text expects str"):
        adapter.tokenize(text=b"bytes")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ChunkingProfile"):
        BgeM3LocalTokenizer(
            profile=object(),  # type: ignore[arg-type]
            tokenizer_assets_dir=tmp_path,
        )
    with pytest.raises(TypeError, match="pathlib.Path"):
        BgeM3LocalTokenizer(
            profile=_profile(),
            tokenizer_assets_dir="assets",  # type: ignore[arg-type]
        )
