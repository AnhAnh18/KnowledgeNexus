# Apply M10 In Five Feature Commits

Prerequisite: M9 patches `001`-`006` have been applied and squashed into one
M9 commit. Keep the worktree clean before every group.

Apply each group in order. After its focused tests pass, squash only that
group. This produces five M10 commits instead of 33 patch commits.

## Group 1 — Snapshot core (patches 007-011, 5 commits)

M10 snapshot wire models, trusted composition, generic completion, and
synthetic acceptance.

```powershell
$patchDir = (Resolve-Path .\patch-transfer-post-m8).Path
7..11 | ForEach-Object { $p = Get-ChildItem $patchDir -Filter ("{0:D3}-*.patch" -f $_); git apply --check $p.FullName }
7..11 | ForEach-Object { $p = Get-ChildItem $patchDir -Filter ("{0:D3}-*.patch" -f $_); git am --no-3way $p.FullName }
python -m pytest tests/foundation/integration/test_m10_synthetic_acceptance.py tests/foundation/domain/models/test_m10_snapshot.py tests/foundation/domain/models/test_m10_composition.py tests/foundation/application/use_cases/test_compose_m10_snapshot.py -q
git reset --soft HEAD~5
git commit -m "feat: complete M10 snapshot core"
```

## Group 2 — Crawl, checkpoint, and OCR policy (patches 012-015, 4 commits)

Bounded crawl orchestration, durable batch sidecar, engine-neutral OCR policy,
and synthetic scale evidence.

```powershell
12..15 | ForEach-Object { $p = Get-ChildItem $patchDir -Filter ("{0:D3}-*.patch" -f $_); git apply --check $p.FullName }
12..15 | ForEach-Object { $p = Get-ChildItem $patchDir -Filter ("{0:D3}-*.patch" -f $_); git am --no-3way $p.FullName }
python -m pytest tests/foundation/domain/models/test_confluence_crawl_batch.py tests/foundation/infrastructure/checkpoint/test_in_memory_confluence_crawl_batch_store.py tests/foundation/infrastructure/checkpoint/test_sqlite_confluence_crawl_batch_store.py tests/foundation/domain/models/test_media_ocr.py -q
git reset --soft HEAD~4
git commit -m "feat: add bounded crawl checkpoint and OCR policy"
```

## Group 3 — Source adapters and gate models (patches 016-021, 6 commits)

M10 Confluence/Git source adapters, external gate envelopes, ACL relation
projection, duplicate-stage protection, and delta tombstone lifecycle.

```powershell
16..21 | ForEach-Object { $p = Get-ChildItem $patchDir -Filter ("{0:D3}-*.patch" -f $_); git apply --check $p.FullName }
16..21 | ForEach-Object { $p = Get-ChildItem $patchDir -Filter ("{0:D3}-*.patch" -f $_); git am --no-3way $p.FullName }
python -m pytest tests/foundation/infrastructure/adapters/test_m10_source_adapters.py tests/foundation/domain/models/test_foundation_gate.py tests/foundation/application/use_cases/test_evaluate_foundation_gates.py tests/foundation/application/use_cases/test_project_tombstones.py -q
git reset --soft HEAD~6
git commit -m "feat: wire M10 source adapters and gate models"
```

## Group 4 — Delta publisher and runtime gates (patches 022-030, 9 commits)

Delta snapshot publication, sanitized CLI results, F4/F7 evaluators, publisher
runtime hardening, safe roots, real-scale transport, and ACL readback gates.

```powershell
22..30 | ForEach-Object { $p = Get-ChildItem $patchDir -Filter ("{0:D3}-*.patch" -f $_); git apply --check $p.FullName }
22..30 | ForEach-Object { $p = Get-ChildItem $patchDir -Filter ("{0:D3}-*.patch" -f $_); git am --no-3way $p.FullName }
python -m pytest tests/foundation/infrastructure/exporters/test_delta_snapshot_reader.py tests/foundation/infrastructure/exporters/test_full_snapshot_publisher.py tests/foundation/application/use_cases/test_evaluate_foundation_gates.py tests/foundation/application/use_cases/test_export_m10_snapshot.py tests/foundation/cli/test_export_m10_snapshot_cli.py -q
git reset --soft HEAD~9
git commit -m "feat: harden M10 delta publisher and runtime gates"
```

## Group 5 — Final projection and Confluence closeout (patches 031-039, 9 commits)

F1-F7 implementation/projection seams, relation closure, bounded delta
orchestration, snapshot readback/sync closure, and final Confluence transport
and generation-bound page publication.

```powershell
31..39 | ForEach-Object { $p = Get-ChildItem $patchDir -Filter ("{0:D3}-*.patch" -f $_); git apply --check $p.FullName }
31..39 | ForEach-Object { $p = Get-ChildItem $patchDir -Filter ("{0:D3}-*.patch" -f $_); git am --no-3way $p.FullName }
python -m pytest tests/foundation/integration/test_m10_synthetic_acceptance.py tests/foundation/domain/rules/test_snapshot_readback.py tests/foundation/infrastructure/adapters/test_m10_composition_root.py tests/foundation/infrastructure/confluence/test_confluence_data_center_attachment_body_adapter.py -q
git reset --soft HEAD~9
git commit -m "feat: complete M10 projection and Confluence closeout"
```

The real M10 full-snapshot run remains an operator-authorized external gate.
Keep captures, credentials, tokenizer bundles, and runtime output outside Git.
