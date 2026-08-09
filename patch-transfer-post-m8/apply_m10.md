# Apply M10 And Closeout

Prerequisite: M9 patches `001`-`006` have been applied and the worktree is
clean. Apply patches `007` through `039` in filename order. This includes
M10-A through M10-E, bounded crawl/checkpoint support, OCR policy, gate
evaluators, delta/readback hardening, and final Confluence transport/page
publication closeout.

```powershell
$patchDir = (Resolve-Path .\patch-transfer-post-m8).Path
7..39 | ForEach-Object { $p = Get-ChildItem $patchDir -Filter ("{0:D3}-*.patch" -f $_); git apply --check $p.FullName }
7..39 | ForEach-Object { $p = Get-ChildItem $patchDir -Filter ("{0:D3}-*.patch" -f $_); git am --no-3way $p.FullName }
```

After the focused tests pass, squash the 33 applied commits into one M10
milestone/closeout commit:

```powershell
git reset --soft HEAD~33
git commit -m "feat: complete M10 snapshot and Foundation closeout"
```

Focused offline verification:

```powershell
python -m pytest tests/foundation/integration/test_m10_synthetic_acceptance.py tests/foundation/domain/models/test_m10_snapshot.py tests/foundation/domain/models/test_m10_composition.py tests/foundation/application/use_cases/test_compose_m10_snapshot.py tests/foundation/application/use_cases/test_export_m10_snapshot.py tests/foundation/cli/test_export_m10_snapshot_cli.py tests/foundation/application/use_cases/test_evaluate_foundation_gates.py tests/foundation/cli/test_evaluate_foundation_gates_cli.py tests/foundation/infrastructure/adapters/test_m10_composition_root.py tests/foundation/infrastructure/adapters/test_m10_source_adapters.py -q
```

The real M10 full-snapshot run remains an operator-authorized external gate.
Keep captures, credentials, tokenizer bundles, and runtime output outside Git.
