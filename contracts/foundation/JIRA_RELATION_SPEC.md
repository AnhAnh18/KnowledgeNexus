# Jira Relation Extraction Contract

Status: active for Foundation M6E.

## Scope

M6E scans exactly one M6C `normalized_body_text` value and emits page-level
`mentions_jira_key` relations. It does not call Jira, parse raw XHTML, inspect
titles or breadcrumbs, or extract media/page-link relations.

The active extraction profile is `jira_relation_profile.yaml`. The configured
regular expression is applied left to right without case conversion, trimming,
repair, or overlapping matches. Only keys whose project component is in
`allowed_project_keys` create relations. Duplicate occurrences create one
relation in first-occurrence order.

A valid Jira macro rendered by M6C is ordinary key text and is therefore in
scope. An invalid or missing Jira macro value rendered as `[jira-issue]` cannot
be recovered by M6E and is out of scope.

## Linkage

Each accepted key produces one `mentions_jira_key` RelationRecord from the
Confluence CanonicalDocument ID to `jira:issue:{key}`. The same ordered Jira
keys and relation IDs are copied to the page CanonicalDocument and all of its
M6D ChunkRecords. Zero accepted keys is valid and leaves these arrays empty.

## Internal observations and metrics

The result keeps first-occurrence-ordered unique broad candidates, allowlisted
keys, and outside-allowlist keys for later quality reporting. These values are
internal and must not appear in CLI output, exception text, or object repr.

Metrics are deterministic and M6E-internal:

- `candidate_occurrences`: all regex matches, including duplicates.
- `unique_key_like_count`: unique broad candidates.
- `allowlisted_unique_count`: unique candidates producing relations.
- `outside_allowlist_unique_count`: unique candidates producing no relation.
- `duplicate_occurrences`: `candidate_occurrences - unique_key_like_count`.
- `relations_total`: emitted RelationRecords.
- `documents_enriched`: one only when at least one relation was linked.
- `chunks_enriched`: input chunk count only when at least one relation was linked.

The result container is frozen and ownership-isolated through recursive
defensive copies. Its schema-shaped nested dictionaries and lists remain plain
mutable JSON values; M6E does not claim deep immutability.
