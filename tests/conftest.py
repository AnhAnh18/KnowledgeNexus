from __future__ import annotations

import sys
from pathlib import Path

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--tokenizer-assets-dir",
        action="store",
        default=None,
        help="Explicit external BGE-M3 tokenizer asset directory",
    )


@pytest.fixture
def tokenizer_assets_dir(request: pytest.FixtureRequest) -> Path:
    raw_path = request.config.getoption("--tokenizer-assets-dir")
    if raw_path is None:
        pytest.fail(
            "asset-backed tokenizer tests require --tokenizer-assets-dir; "
            "they must not skip or use an implicit cache"
        )
    path = Path(raw_path)
    if not path.is_dir():
        pytest.fail("--tokenizer-assets-dir must identify an existing directory")
    return path

