# M10-B Independent Review (Final)

Review target: current M10-B fix implementation in `m10_composition.py`,
`compose_m10_snapshot.py`, and related exports. This review was performed in a
fresh session without editing implementation files.

## Findings

- **P1 - Record shape is trusted to an injected validator and malformed records can escape the application boundary.** `_validate_records` (`src/knowledgenexus/foundation/domain/models/m10_composition.py:123-140`) only deep-copies records and calls the injected `validate_record`; it does not enforce the schema field sets/runtime containers itself. With a validator that returns successfully without validating, a document containing an extra field is projected successfully, while a document missing `source_system` reaches the direct indexing at line 170 and raises raw `KeyError`. `ComposeM10Snapshot.execute` (`src/knowledgenexus/foundation/application/use_cases/compose_m10_snapshot.py:81-84`) catches only `TypeError`, `ValueError`, and `M10SnapshotError`, so that malformed input is neither rejected before field access nor sanitized as a projection failure.

- **P1 - Git chunk file paths are not checked against the required POSIX path grammar.** The Git chunk branch (`src/knowledgenexus/foundation/domain/models/m10_composition.py:197-207`) checks repository, branch, commit, and ACL tags but never calls `_path` for `file_path`. The `ChunkRecord` schema permits arbitrary strings (including `../escape` and backslashes), so a schema-valid chunk with traversal/Windows separators can compose successfully, violating the approved Git documents/chunks path provenance contract.

- **P1 - Unresolved non-Jira relations accept the forbidden fabricated `unknown` target.** Relation checks (`src/knowledgenexus/foundation/domain/models/m10_composition.py:208-221`) require only a non-empty target that is not emitted for non-resolved statuses. A schema-valid `embeds_media`/`unresolved_target` relation with `target_id="unknown"` therefore succeeds, despite the plan explicitly forbidding missing, fabricated, `unknown`, or contradictory targets.

- **P2 - Source ownership is not bound to the originating handoff.** The two handoff streams are concatenated before projection validation (`src/knowledgenexus/foundation/domain/models/m10_composition.py:160`), and records are accepted solely from their claimed `source_system` and request metadata. A Git handoff can therefore carry a valid Confluence document/chunk/ACL/media record (or vice versa) and be emitted; the typed adapter boundary does not enforce that each record came from its source-specific handoff.

## Validation Evidence

- Focused M10-A/M10-B tests: `42 passed` (implementation artifact).
- Bounded M9 regression: `120 passed` (implementation artifact).
- Bounded architecture regression: `88 passed` (implementation artifact).
- Focused independent rerun of M10 composition/use-case tests: `19 passed`.
- `compileall -q src tests` and `git diff --check`: passed per implementation artifact.
- Additional adversarial probe with a no-op injected validator confirmed extra-field acceptance and raw `KeyError` leakage for a missing required field.

VERDICT: CHANGES_REQUIRED
