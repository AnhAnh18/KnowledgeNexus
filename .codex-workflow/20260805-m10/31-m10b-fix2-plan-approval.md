RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# M10-B Fix2 Plan Approval

The final fix2 plan resolves the prior review requirements and is ready for
bounded implementation.

- It explicitly treats M10 as seven schema-validated non-tombstone streams
  plus an exactly empty tombstone stream, with canonical validation before
  field access and isolated-copy mutation detection for both validators.
- It defines Confluence and Git handoff ownership, including page/attachment
  versus file/repo sync rows and rejection of cross-source records.
- It applies the approved POSIX path grammar to Git documents, chunks, and
  symbols.
- It enumerates unresolved relation target grammars for Jira issues,
  Confluence pages, and attachments; rejects empty/placeholder/fabricated
  targets and requires emitted targets for resolved relations.
- It preserves ACL inheritance, media raw/content provenance and budgets, sync
  version/cardinality, deterministic ordering, exact metrics/results, adapter
  callability, and sanitized atomic failures.
- Acceptance coverage includes canonical/no-op validator bypass, construction
  and mutation failures, missing-field sanitization, ownership drift,
  placeholder variants, zero calls, regressions, and independent review.

No scope expansion beyond M10-B and the approved M10-A compatibility fix is
introduced.

VERDICT: PASS
