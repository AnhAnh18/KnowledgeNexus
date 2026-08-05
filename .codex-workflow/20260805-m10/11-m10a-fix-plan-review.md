RECOMMENDED_IMPLEMENTATION_PROFILE: build

# M10-A Boundary Validation Fix - Reviewed

The fix plan is correctly scoped to the confirmed P1/P2 findings and is
buildable as a localized model-validation change. The following details are
required for an implementation and re-review to verify the boundary rather
than only the reported examples.

## Required implementation

1. Add exact expected runtime field sets and a sentinel-safe helper for every
   public model: `M10ConfluenceScope`, `M10ConfluenceExclusion`,
   `M10MediaPolicy`, `M10SnapshotRequest`, `M10SnapshotMetrics`,
   `M10SnapshotProjection`, `M10SnapshotResult`, and `M10QualityReportInput`.
   Check the exact concrete type and field set before reading any attribute;
   missing fields, forbidden extras, and forged nested models must raise only
   sanitized `TypeError`/`ValueError`. Revalidate nested models explicitly
   before dereferencing their fields, and preserve defensive-copy and frozen
   semantics.

2. Replace all timestamp checks at the M10-A model boundary with one strict
   RFC3339 grammar: `YYYY-MM-DDTHH:MM:SS`, optional fractional seconds, and a
   required `Z` or numeric `+/-HH:MM` offset. Reject date-only, naive,
   whitespace, lowercase/invalid zones, invalid calendar values, and wrong
   runtime types before `datetime` access. Preserve the caller's canonical
   timestamp string byte-for-byte; do not normalize it in the model.

3. Make dataset-root validation reject symlinks and Windows reparse points
   while retaining absolute plain-directory and containment checks. Use a
   platform-safe attribute check (`FILE_ATTRIBUTE_REPARSE_POINT` when
   available) and sanitize all filesystem errors to the model's typed
   validation error. Tests must use temporary fixtures or a mocked file-attribute
   result; never mutate arbitrary workspace paths.

## Required adversarial tests

- Parameterize every required field as missing and a forbidden extra field for
  all eight models. Include `object()`, `None`, wrong containers/types/enums,
  forged frozen instances, and malformed nested model instances; assert only
  `TypeError`/`ValueError` and no leaked `AttributeError`.
- Cover impossible cross-field combinations: scope membership/order and
  duplicate IDs, exclusion ordering/duplicates, media-policy enum/budget
  combinations, request run/generation and page-scope identity, metrics
  counters, projection stream/count/config/chunker invariants, result
  status-field combinations and digest, and quality-input count/section
  mappings. Assert malformed inputs fail before any dependency or filesystem
  side effect.
- Add a timestamp matrix for valid `Z` and offset forms (including fractional
  seconds) and invalid naive/date-only/zone/calendar/string-subclass values;
  assert accepted strings are preserved exactly.
- Add Windows reparse-point coverage by simulating the reparse attribute on a
  temporary dataset root (with a non-Windows skip only when the platform API
  cannot be exercised), plus symlink and non-directory roots. Assert fail
  closed without creating, deleting, or mutating files.

## Scope and verification

Production changes are limited to M10-A model validation and its focused tests;
do not touch exporters, CLI, orchestration, roadmap/state, or M8/M9 code.
Run the focused suite with an explicit artifact basetemp, then compile and
diff checks, and obtain a fresh independent re-review before any broader M10
stage:

`$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/models/test_m10_snapshot.py --basetemp=.codex-workflow/20260805-m10/pytest-m10a-fix`

`python -m compileall -q src tests`; `git diff --check`

Acceptance requires all malformed model probes to fail with sanitized typed
errors, strict timezone-aware RFC3339 preservation, Windows reparse/symlink
rejection, and no out-of-scope source changes. A fresh independent review must
report `VERDICT: PASS` before roadmap/state updates or commit.
