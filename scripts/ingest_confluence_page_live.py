"""Fetch 1 trang Confluence THẬT (live), rồi chunk + embed + lưu vào Qdrant/SQLite.

Khác với scripts/ingest_confluence_page.py (chỉ đọc trang đã crawl sẵn từ
raw_root), script này THẬT SỰ gọi mạng ra server Confluence nội bộ để lấy
đúng 1 trang theo page_id trong --url, rồi lưu raw page đó vào --raw-root
(để tái dùng IngestConfluencePage y hệt luồng offline), sau đó chunk + embed
+ ingest vào Qdrant + SQLite — không qua file JSON trung gian.

Đây là script chạy tay 1 lần (demo/thử nghiệm thủ công), KHÔNG phải một
phần của bulk crawler (inventory/capture-pages trong
confluence_subtree_corpus.py) — chỉ fetch đúng 1 page_id đã biết trước,
không quét cả subtree/space.

Yêu cầu — đặt trong file .env ở gốc repo (không commit, đã trong .gitignore):
    CONFLUENCE_BASE_URL   (vd: https://confluence-mx.sec.samsung.net)
    CONFLUENCE_PAT        (Personal Access Token của bạn)
    EMBEDDING_MODEL_PATH  (thư mục chứa tokenizer.json BGE-M3, vd: D:\\Tools\\BAAI_bge-m3)
Ngoài ra: Qdrant server đang chạy; pip install qdrant-client pyyaml FlagEmbedding.

Chạy (mọi tham số đều lấy mặc định từ .env, chỉ cần chạy suông):
    python scripts/ingest_confluence_page_live.py

Hoặc ghi đè bất kỳ tham số nào nếu cần:
    python scripts/ingest_confluence_page_live.py \\
        --url "https://confluence-mx.sec.samsung.net/spaces/SVMC/pages/2113438062/SPen+Work+principles" \\
        --raw-root "./data/confluence-raw" \\
        --profile-path "contracts/foundation/embedding_profile.yaml" \\
        --tokenizer-assets-dir "D:\\Tools\\BAAI_bge-m3"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from knowledgenexus.foundation.application.use_cases.fetch_confluence_page_live import (
    fetch_confluence_page_live,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.rules.confluence_url import (
    ConfluenceUrlParseError,
    parse_confluence_page_id,
)
from knowledgenexus.foundation.infrastructure.config.chunking_profile_loader import (
    load_chunking_profile,
)
from knowledgenexus.foundation.infrastructure.processors import (
    ConfluenceDataCenterRawPageMapper,
    ConfluenceStorageXhtmlNormalizer,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluenceRawPageGenerationStore,
)
from knowledgenexus.foundation.infrastructure.tokenization import BgeM3LocalTokenizer
from knowledgenexus.indexing.application.use_cases.ingest_confluence_page import (
    IngestConfluencePage,
)
from knowledgenexus.shared.config.settings import Settings
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)
from knowledgenexus.shared.di.container import build_container

# Đường dẫn mặc định đã xác nhận có sẵn trên máy dev hiện tại — vẫn có thể
# ghi đè bằng flag tương ứng nếu chạy trên máy khác.
_DEFAULT_URL = (
    "https://confluence-mx.sec.samsung.net/spaces/SVMC/pages/2113438062/"
    "SPen+Work+principles"
)
_DEFAULT_RAW_ROOT = _REPO_ROOT / "data" / "confluence-raw"
_DEFAULT_PROFILE_PATH = _REPO_ROOT / "contracts" / "foundation" / "embedding_profile.yaml"


def _parse_args(*, default_tokenizer_assets_dir: str | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=_DEFAULT_URL, help="Link trang Confluence (thật)")
    parser.add_argument(
        "--raw-root",
        default=str(_DEFAULT_RAW_ROOT),
        help=f"Thư mục lưu raw page vừa fetch (mặc định {_DEFAULT_RAW_ROOT})",
    )
    parser.add_argument(
        "--profile-path",
        default=str(_DEFAULT_PROFILE_PATH),
        help=f"File chunking profile YAML (mặc định {_DEFAULT_PROFILE_PATH})",
    )
    parser.add_argument(
        "--tokenizer-assets-dir",
        default=default_tokenizer_assets_dir,
        required=default_tokenizer_assets_dir is None,
        help=(
            "Thư mục chứa tokenizer.json BGE-M3 "
            f"(mặc định lấy từ EMBEDDING_MODEL_PATH trong .env = {default_tokenizer_assets_dir})"
        ),
    )
    return parser.parse_args()


async def main() -> int:
    settings = Settings()
    args = _parse_args(default_tokenizer_assets_dir=settings.embedding_model_path)

    print("=" * 70)
    print("Fetch LIVE 1 trang Confluence -> chunk -> embed -> Qdrant + SQLite")
    print("=" * 70)

    base_url = settings.confluence_base_url
    pat = settings.confluence_pat
    if not base_url or not pat:
        print("[ERROR] Cần đặt CONFLUENCE_BASE_URL và CONFLUENCE_PAT trong .env trước khi chạy.")
        return 1

    try:
        page_id = parse_confluence_page_id(args.url)
    except ConfluenceUrlParseError as exc:
        print(f"[ERROR] Không lấy được page_id từ URL: {exc}")
        return 1
    print(f"[OK] page_id = {page_id}")

    raw_root = Path(args.raw_root).resolve()
    raw_root.mkdir(parents=True, exist_ok=True)
    run_id = CrawlRunId(str(uuid4()))
    print(f"[OK] run_id (mới, dùng cho lần fetch này) = {run_id}")

    print(f"\n[1/4] Fetch live từ {base_url} ...")
    try:
        fetch_confluence_page_live(
            base_url=base_url, pat=pat, run_id=run_id, page_id=page_id, raw_root=raw_root
        )
    except Exception as exc:
        print(f"[ERROR] Fetch live thất bại: {type(exc).__name__}: {exc}")
        return 1
    print(f"[OK] Đã lưu raw page vào {raw_root}")

    print("\n[2/4] Nạp chunking profile + tokenizer...")
    profile = load_chunking_profile(Path(args.profile_path))
    tokenizer = BgeM3LocalTokenizer(
        profile=profile, tokenizer_assets_dir=Path(args.tokenizer_assets_dir)
    )
    print(f"[OK] profile={profile.active_profile}, chunker={profile.chunker_version}")

    print("\n[3/4] Khởi tạo embedder + Qdrant + SQLite...")
    container = await build_container(settings)
    print(f"[OK] Qdrant: {settings.qdrant_url}, collection: {settings.qdrant_collection}")

    use_case = IngestConfluencePage(
        chunking_profile=profile,
        tokenizer=tokenizer,
        raw_page_store=ConfluenceRawPageGenerationStore(raw_root=raw_root),
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
        schema_validator=FoundationSchemaValidator(),
        embedder=container.get_embedder(),
        chunk_storage_service=container.chunk_storage,
    )

    print("\n[4/4] Chunk + embed + lưu...")
    try:
        result = await use_case.execute(run_id=run_id, page_id=page_id)
    finally:
        await container.shutdown()

    print("\n" + "=" * 70)
    print(
        json.dumps(
            {
                "status": result.status,
                "chunks_ingested": result.chunks_ingested,
                "chunks_failed": result.chunks_failed,
                "source_id": result.source_id,
                "embedding_model": result.embedding_model,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("=" * 70)
    return 0 if result.status in ("success", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
