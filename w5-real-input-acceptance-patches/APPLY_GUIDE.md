# W5 real-input acceptance patch guide

Apply this stack only after the approved W4-C2 production/test tree is present.
The source-review W5 planning commit is not required: it changed only
`docs/learning/W5_OPERATOR_ACCEPTANCE_PROMPT.md`.

## Patch order

```powershell
git apply --check .\w5-real-input-acceptance-patches\0001-W5-A-foundation-add-controlled-real-input-acceptance.patch
git apply .\w5-real-input-acceptance-patches\0001-W5-A-foundation-add-controlled-real-input-acceptance.patch

git apply --check .\w5-real-input-acceptance-patches\0002-W5-A-docs-make-W5-execution-packets-runnable.patch
git apply .\w5-real-input-acceptance-patches\0002-W5-A-docs-make-W5-execution-packets-runnable.patch

git apply --check .\w5-real-input-acceptance-patches\0003-W5-A-FIX-foundation-make-controlled-Root-1-acceptanc.patch
git apply .\w5-real-input-acceptance-patches\0003-W5-A-FIX-foundation-make-controlled-Root-1-acceptanc.patch
```

Do not use `--reject`, whitespace repair, or manual conflict resolution without
review. `src/knowledgenexus/foundation/cli/confluence_subtree_corpus.py` is the
only file shared with W4-C2; this stack was generated from the approved W4-C2
lineage and was separately validated by applying it to the W4-C2 head.

## Verification

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'

py -3.12 -m pytest `
  tests/foundation/application/use_cases/test_confluence_subtree_capture_resume.py `
  tests/foundation/cli/test_confluence_subtree_cli.py `
  tests/foundation/integration/test_w5_a_runbook_artifacts.py `
  tests/foundation/application/use_cases/test_evaluate_foundation_gates.py `
  tests/foundation/cli/test_evaluate_foundation_gates_cli.py `
  tests/foundation/domain/models/test_foundation_gate.py `
  tests/architecture -q

py -3.12 -m compileall -q src tests
git diff --check
git status --short
```

Expected focused result from the source-review environment: `173 passed`.
Use the available Python 3.12/3.13 executable on the main machine; changing the
interpreter launcher does not change the acceptance contract.

## Suggested commits on the main machine

Create one commit after each patch, preserving the subjects embedded in the
patch files:

```text
[W5-A] foundation: add controlled real-input acceptance runbooks
[W5-A] docs: make W5 execution packets runnable
[W5-A-FIX] foundation: make controlled Root-1 acceptance executable
```

These patches authorize no live request. W5-B live execution still requires a
separate owner authorization and the operator preflight in
`docs/runbooks/W5_B_ROOT1_FULL_SNAPSHOT.md`.
