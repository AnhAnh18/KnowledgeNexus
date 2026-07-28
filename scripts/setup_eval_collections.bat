@echo off
REM ============================================================
REM Setup eval test collections for dense vs hybrid A/B comparison
REM
REM Usage:
REM   scripts\setup_eval_collections.bat
REM
REM This script will:
REM   1. Create knowledgenexus_dense_test collection (dense only)
REM   2. Ingest eval corpus into dense collection
REM   3. Create knowledgenexus_hybrid_test collection (dense + sparse)
REM   4. Ingest eval corpus into hybrid collection
REM
REM Prerequisites:
REM   - Qdrant running at http://localhost:6333
REM   - BGE-M3 model at EMBEDDING_MODEL_PATH (see .env)
REM   - Eval corpus at data/eval/corpus/*.md
REM
REM After eval, cleanup with:
REM   python scripts/delete_collection.py --name knowledgenexus_dense_test
REM   python scripts/delete_collection.py --name knowledgenexus_hybrid_test
REM ============================================================

setlocal

echo ============================================================
echo  Setup Eval Test Collections (Dense + Hybrid)
echo ============================================================
echo.

REM ---- 1. Dense test collection ----
echo [1/4] Creating dense test collection: knowledgenexus_dense_test
python scripts/create_collection.py --config config/qdrant.collection.yaml --name knowledgenexus_dense_test
if errorlevel 1 (
    echo [FAIL] Failed to create dense collection
    exit /b 1
)
echo.

echo [2/4] Ingesting eval corpus into dense collection...
set "QDRANT_COLLECTION=knowledgenexus_dense_test"
set "RETRIEVAL_MODE=dense"
python scripts/ingest_eval_corpus.py
if errorlevel 1 (
    echo [FAIL] Failed to ingest dense corpus
    exit /b 1
)
echo.

REM ---- 2. Hybrid test collection ----
echo [3/4] Creating hybrid test collection: knowledgenexus_hybrid_test
python scripts/create_collection.py --config config/qdrant.collection.hybrid.yaml --name knowledgenexus_hybrid_test
if errorlevel 1 (
    echo [FAIL] Failed to create hybrid collection
    exit /b 1
)
echo.

echo [4/4] Ingesting eval corpus into hybrid collection...
set "QDRANT_COLLECTION=knowledgenexus_hybrid_test"
set "RETRIEVAL_MODE=hybrid"
python scripts/ingest_eval_corpus.py
if errorlevel 1 (
    echo [FAIL] Failed to ingest hybrid corpus
    exit /b 1
)
echo.

echo ============================================================
echo  Done! Test collections ready for A/B eval.
echo ============================================================
echo.
echo  Next steps:
echo    1. Start API with dense collection:
echo       set QDRANT_COLLECTION=knowledgenexus_dense_test ^&^& set RETRIEVAL_MODE=dense ^&^& set KNOWLEDGENEXUS_API_URL=http://localhost:8000 ^&^& python -m knowledgenexus.main
echo.
echo    2. Run dense eval:
echo       set "KNOWLEDGENEXUS_API_URL=http://localhost:8000" ^&^& set "KNOWLEDGENEXUS_RETRIEVAL_MODE=dense" ^&^& python -m knowledgenexus.eval.runner --layer 1 --label dense-baseline
echo.
echo    3. Stop API, restart with hybrid collection:
echo       set QDRANT_COLLECTION=knowledgenexus_hybrid_test ^&^& set RETRIEVAL_MODE=hybrid ^&^& set KNOWLEDGENEXUS_API_URL=http://localhost:8000 ^&^& python -m knowledgenexus.main
echo.
echo    4. Run hybrid eval:
echo       set "KNOWLEDGENEXUS_API_URL=http://localhost:8000" ^&^& set "KNOWLEDGENEXUS_RETRIEVAL_MODE=hybrid" ^&^& python -m knowledgenexus.eval.runner --layer 1 --label hybrid-rrf
echo.
echo    5. Compare results:
echo       python scripts/compare_eval_results.py --label1 dense-baseline --label2 hybrid-rrf --output data/eval/results/ab_comparison.md
echo.
echo    6. Cleanup:
echo       python scripts/delete_collection.py --name knowledgenexus_dense_test
echo       python scripts/delete_collection.py --name knowledgenexus_hybrid_test
echo.

endlocal
