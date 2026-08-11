# W5-A - real-input acceptance inspection and runbook candidate

This is the portable, local-only W5-A handoff. It prepares the main-machine
execution packets but performs no Confluence request. Keep raw generations,
credentials, tokenizer files, and runtime evidence outside this repository.

## Boundary and stop conditions

- Run from a frozen committed head with a clean tracked tree.
- Use only metadata from external artifacts; never copy page IDs, titles,
  URLs, hostnames, paths, raw bodies, principals, credentials, or full hashes
  into Git or a review message.
- W5-B and W5-C are separate owner-authorized live operations. This document
  does not authorize either operation.
- Stop if transfer equivalence, profile/tokenizer verification, safe output
  roots, Draw.io-only gate coverage, or sanitization cannot be proven.

## Local inspection

From the repository root, verify the expected W5 base and branch without
printing sensitive paths:

```powershell
git rev-parse HEAD
git diff --quiet
git diff --cached --quiet
git diff --check
```

The execution head must be the reviewed W5-A commit (or a later approved
commit). The main-machine operator records its own `MAIN_EXECUTION_HEAD`; SHA
values are kept in local provenance and are not included in sanitized evidence.

Inspect the transferred W4 production, contract, and test paths by comparing
scoped Git blobs, not by trusting branch names:

```powershell
git ls-tree -r --full-tree HEAD -- <scoped-paths>
git -C <main-checkout> ls-tree -r --full-tree <main-transfer-head> -- <scoped-paths>
```

The operator must retain the comparison privately and return only:
`transfer_equivalent=true|false`, `scoped_path_count`, and a sanitized failure
category when false. Do not return the path list or blob hashes.

## Profile and asset preflight

Use the exact committed `contracts/foundation/crawl_reliability_profile.yaml`
and `contracts/foundation/embedding_profile.yaml`. The BGE-M3 bundle must be
an explicit external directory matching the committed profile; implicit cache
or network fallback is forbidden. If the bundle is absent, asset-backed tests
must fail or be reported not run, never silently skip as passed.

```powershell
$env:PYTHONUTF8 = "1"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
python -m compileall -q src tests
```

## Draw.io-only gate inspection

W5 text-first acceptance uses the explicit `drawio_only` coverage profile. The
default media gate remains `all_media` and still requires all five historical
media kinds. The Draw.io-only profile accepts only Draw.io outcomes and never
activates OCR, PDF, image, chart, audio, or video processing.

```powershell
python -m pytest tests/foundation/application/use_cases/test_evaluate_foundation_gates.py -q
```

## Offline preflight matrix

Run the required offline suites with the explicit tokenizer option when the
bundle exists. Keep the command output aggregate-only.

```powershell
python -m pytest `
  tests/foundation/cli/test_w4_c2_composition.py `
  tests/foundation/cli/test_confluence_subtree_cli.py `
  tests/foundation/cli/test_export_m10_snapshot_cli.py `
  tests/foundation/cli/test_m10_operator_cli_e2e.py `
  tests/foundation/application/use_cases/test_capture_delta_inventory.py `
  tests/foundation/application/use_cases/test_project_m10_delta.py `
  tests/foundation/application/use_cases/test_export_m10_snapshot.py `
  tests/foundation/infrastructure/exporters/test_delta_snapshot_reader.py `
  tests/foundation/domain/rules/test_snapshot_readback.py `
  tests/architecture -q
```

Record only pass/fail counts, skipped asset-backed tests, `compileall`,
`git diff --check`, and tracked-tree status in the W5-A notice.

## Handoff

After independent W5-A approval and the W5-A commit is pushed, give the main
machine operator `W5_B_ROOT1_FULL_SNAPSHOT.md`. Stop and wait for explicit
owner authorization. After sanitized W5-B evidence is returned and reconciled,
give the operator `W5_C_SECOND_SYNC_DELTA.md`. No live phase is executed from
the local repository.
