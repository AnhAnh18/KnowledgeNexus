RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# M10-B Revised Fix Plan Review

The revised plan materially addresses the findings in `19-m10b-review-1.md`
and the clarification requests in `21-m10b-fix-plan-review.md`. It is close to
implementable, but the following requirements remain necessary for an
unambiguous, reviewable fix.

## Required Corrections

- Correct the validator wording: the listed schemas cover seven non-tombstone
  streams (documents, chunks, relations, ACL, media, symbols, sync), while
  M10 has eight total streams including the forbidden initial tombstone
  stream. State this explicitly and require the tombstone tuple to remain
  exactly empty.
- For Git ACLs, state that `restricted:unresolved` is deny-safe only as a
  failure condition for the initial successful projection (or otherwise define
  the exact allowed-success behavior). The approved plan says a Git ACL that
  cannot establish `repo:<repository>` fails the deny-safe gate; accepting a
  restricted tag in a successful projection would violate that contract.
- Add explicit media raw/content provenance fields and equality rules. Parent
  ID and source version alone do not prove the media body/raw artifact is tied
  to the selected source; require the approved provenance identity and reject
  drift or missing values.
- Enumerate all relation statuses and their target rules, not only
  `mentions_jira_key`/`unresolved_target`: define required target/source fields
  for `resolved`, `unresolved_without_jira_api`, `deferred_mvp`, and
  `unresolved_target`, and forbid contradictory unresolved markers on resolved
  records.
- State the sync cardinality rule precisely: no duplicate entity rows, no
  `error`/`tombstoned`, and at most/exactly one active row for each selected
  page/file/repo/attachment entity as applicable. Require schema version,
  source/entity/version equality and reject rows for non-emitted entities.
- Define deterministic ordering requirements for each merged stream and
  ensure selected Confluence page ordering is checked against the request, not
  merely membership in `ordered_page_ids`.

## Risks / Acceptance

- Keep schema validation before every record field access and validate isolated
  deep copies; prove validator mutation and arbitrary exceptions produce a
  sanitized atomic projection failure with no partial streams.
- Require invalid request/adapter cases to make zero adapter calls, and assert
  non-callable validators/adapters fail at construction. Add direct forged
  `M10CompositionResult` missing/extra-field probes.
- Preserve M6G/M9 schemas and bytes exactly; run focused M10-A/M10-B tests,
  bounded M9/M6G and architecture suites, compileall, diff-check, then obtain
  a fresh independent review before roadmap/state changes.

VERDICT: CHANGES_REQUIRED
