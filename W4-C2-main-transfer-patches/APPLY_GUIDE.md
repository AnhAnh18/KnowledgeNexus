# W4-C2 main-machine transfer

This stack transfers independently approved W4-C2 from approved W4-C1 source
head `966857e` through W4 final source head `cec2a8c`.

Main-machine commit IDs may differ. Apply the patches to a clean tree that
already contains the complete approved W4-C1 tree. Do not require the
source-review SHAs to exist in the main-machine history.

## Apply in order

```powershell
$patches = @(
  @('0001-W4-C2-foundation-expose-operator-runnable-M10-delta-.patch', '[W4-C2] foundation: expose operator-runnable M10 delta publication'),
  @('0002-W4-C2-FIX-foundation-bind-ancestor-exclusion-scope-i.patch', '[W4-C2-FIX] foundation: bind ancestor exclusion scope identity'),
  @('0003-W4-C2-FIX2-foundation-reject-delta-only-full-mode-fl.patch', '[W4-C2-FIX2] foundation: reject delta-only full-mode flags'),
  @('0004-W4-C2-FIX3-foundation-harden-injected-delta-composit.patch', '[W4-C2-FIX3] foundation: harden injected delta composition'),
  @('0005-W4-C2-FIX3-TEST-foundation-update-sanitized-output-a.patch', '[W4-C2-FIX3-TEST] foundation: update sanitized output assertion'),
  @('0006-W4-C2-FIX4-PROD-foundation-accept-platform-path-subc.patch', '[W4-C2-FIX4-PROD] foundation: accept platform path subclasses'),
  @('0007-W4-C2-FIX4-TEST-foundation-lock-operator-delta-compo.patch', '[W4-C2-FIX4-TEST] foundation: lock operator delta composition'),
  @('0008-W4-C2-FIX5-PROD-foundation-harden-real-delta-readbac.patch', '[W4-C2-FIX5-PROD] foundation: harden real delta readback path'),
  @('0009-W4-C2-FIX5-TEST-foundation-lock-offline-delta-operat.patch', '[W4-C2-FIX5-TEST] foundation: lock offline delta operator publication')
)

foreach ($item in $patches) {
  $patch = $item[0]
  $message = $item[1]
  git apply --check ".\$patch"
  if ($LASTEXITCODE -ne 0) { throw "Patch precheck failed: $patch" }
  git apply ".\$patch"
  if ($LASTEXITCODE -ne 0) { throw "Patch apply failed: $patch" }
  git add src tests
  git commit -m $message
  if ($LASTEXITCODE -ne 0) { throw "Commit failed: $patch" }
}
```

Stop on the first failure. Do not use `--reject`, omit hunks, or continue from
a partially applied C2 stack.

## Files transferred

```text
src/knowledgenexus/foundation/application/use_cases/project_m10_delta.py
src/knowledgenexus/foundation/cli/confluence_subtree_corpus.py
src/knowledgenexus/foundation/cli/export_m10_snapshot.py
src/knowledgenexus/foundation/infrastructure/exporters/delta_snapshot_reader.py
src/knowledgenexus/foundation/infrastructure/sidecars/delta_inventory_artifact_store.py
tests/foundation/cli/test_export_m10_snapshot_cli.py
tests/foundation/cli/test_m10_operator_cli_e2e.py
tests/foundation/cli/test_w4_c2_composition.py
```

## Offline verification

```powershell
$env:PYTHONUTF8 = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'

py -3 -m pytest `
  tests/foundation/application/use_cases/test_capture_delta_inventory.py `
  tests/foundation/application/use_cases/test_classify_delta_inventory.py `
  tests/foundation/application/use_cases/test_propagate_delta.py `
  tests/foundation/application/use_cases/test_project_m10_delta.py `
  tests/foundation/application/use_cases/test_export_m10_snapshot.py `
  tests/foundation/infrastructure/exporters/test_delta_snapshot_reader.py `
  tests/foundation/domain/rules/test_snapshot_readback.py `
  tests/foundation/cli/test_export_m10_snapshot_cli.py `
  tests/foundation/cli/test_m10_operator_cli_e2e.py `
  tests/foundation/cli/test_confluence_subtree_cli.py `
  tests/foundation/cli/test_w4_c2_composition.py `
  tests/architecture -q

py -3 -m compileall -q src tests
git diff --check
git status --short
```

Reviewed source results:

```text
focused/final suite: 141 passed
fresh independent review suite: 145 passed
compileall: pass
git diff --check: pass
open P0/P1/P2: none
```

Do not run live Confluence during patch transfer. W5 real-input execution is a
separate, explicitly authorized operator task.
