# Optional Post-M8 Patch Transfer

This directory is an optional transfer artifact. It is safe to skip entirely;
it is not product behavior and is not a required milestone commit.

Baseline: the target machine already contains M8-AC, M8-AX, and M9-A1. Apply
from a clean target worktree. `manifest.json` is authoritative for the exact
source SHA, subject, and patch filename.

## Apply safely

```powershell
git status --short
Get-ChildItem .\patch-transfer-post-m8\*.patch | ForEach-Object { git apply --check $_.FullName }
```

Apply patches in filename order with `git am --no-3way`, preserving one logical
commit per patch while applying against the target's M9-A1-resolved tree. If
any patch conflicts, stop and run `git am --abort`; do not force-apply it. Run
`apply_m9.md` first, then `apply_m10.md`.

The series intentionally excludes M8-only commits, M9-A1 (already present),
and the M8-AC receipt-only documentation patch. It contains no runtime data,
credentials, tokenizer assets, or live captures.

The bundle commit itself is explicitly optional, e.g.
`[OPTIONAL] chore: add post-M8 patch transfer bundle`; Gemini may ignore that
commit and copy/apply the patch files through another channel.
