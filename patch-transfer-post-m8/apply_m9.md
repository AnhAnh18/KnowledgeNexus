# Apply M9

Prerequisite: M8-AC, M8-AX, and M9-A1 are present; the worktree is clean.

Apply patches `001` through `006` in order. `manifest.json` lists the exact
commit mapping.

```powershell
$patchDir = (Resolve-Path .\patch-transfer-post-m8).Path
1..6 | ForEach-Object { $p = Get-ChildItem $patchDir -Filter ("{0:D3}-*.patch" -f $_); git apply --check $p.FullName }
1..6 | ForEach-Object { $p = Get-ChildItem $patchDir -Filter ("{0:D3}-*.patch" -f $_); git am --no-3way $p.FullName }
```

Focused offline verification:

```powershell
python -m pytest tests/foundation/domain/models/test_media_materialization.py tests/foundation/domain/models/test_media_body_materialization.py tests/foundation/domain/models/test_media_processing.py tests/foundation/infrastructure/processors/test_media_attachment_processors.py tests/foundation/application/use_cases/test_process_confluence_media_attachment.py tests/foundation/application/use_cases/test_build_git_symbols.py tests/foundation/domain/models/test_symbol_index.py tests/foundation/domain/models/test_tombstone_propagation.py tests/foundation/domain/models/test_delta_propagation.py -q
```

No live network or credentials are needed for these tests.
