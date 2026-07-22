# M6E working-tree review notice

Status: committed candidate stack ready for detached review.

Base commit: `e33626155f7017fc17e3521876064d2e130ee26f`

## Scope and public surface

M6E implements regex-only page-level Jira relation extraction and linkage. It
does not start M6F.

Public contract/model/config surface:

```text
contracts/foundation/JIRA_RELATION_SPEC.md
contracts/foundation/jira_relation_profile.yaml

JiraRelationProfile(
    schema_version,
    extraction_mode,
    key_pattern,
    allowed_project_keys,
)

load_jira_relation_profile(profile_path: Path) -> JiraRelationProfile

BuildConfluenceJiraRelations.execute(
    *,
    normalized_body_text: str,
    canonical_document: Mapping[str, object],
    chunking_result: ChunkingResult,
    created_at: str,
) -> ConfluenceJiraRelationResult
```

The result is a frozen `repr=False` ownership-isolated container holding the
enriched CanonicalDocument, ordered enriched ChunkRecords, ordered
RelationRecords, internal quality observation, and aggregate metrics. Nested
schema-shaped JSON dictionaries/lists deliberately remain mutable; deep
immutability is not claimed.

## Locked behavior

- Exact standalone-token regex:
  `(?<![A-Za-z0-9_])(?P<key>[A-Z][A-Z0-9_]+-[0-9]+)(?![A-Za-z0-9_])`.
- Scan source is exactly M6C `normalized_body_text`; no raw/XHTML/title/chunk
  scanning and no case conversion, trimming, or repair.
- Broad candidates, allowlisted keys, and outside-allowlist keys retain first
  occurrence order. Duplicate occurrences produce one relation.
- Active allowlist is configuration-driven and contains `SVMCSPEN`.
- Valid Jira macros already rendered by M6C as text are covered. Invalid or
  omitted macro shapes rendered as `[jira-issue]` are not recovered.
- Relation mapping is page-level `mentions_jira_key`, with target identity built
  by `DocumentIdGenerator.source_entity_id`, deterministic IDs from
  `RelationIdGenerator`, evidence `regex:page_body`, confidence `0.95`, status
  `unresolved_without_jira_api`, and explicit `created_at`.
- The same ordered keys/relation IDs propagate to every corresponding M6D
  chunk. Zero relations is valid and leaves all linkage arrays empty.
- Entry checks bind normalized body hash to the CanonicalDocument, enforce
  canonical normalization, verify canonical page identity, require exact M6D
  provenance fields, unique chunk IDs, chunk text hashes, and chunk count
  coherence. Full chunk-ID re-derivation is intentionally out of scope because
  M6D unit keys are not retained.
- Input dictionaries/lists are not mutated. All non-link canonical/chunk fields,
  content hashes, token counts, identities, order, and ACL tags remain exact.
- True different-preimage relation-ID collisions fail; relation IDs have no
  suffix behavior.

## Verification

Environment:

```text
Python 3.12 isolated review venv
PYTHONUTF8=1
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
exact pinned BGE-M3 tokenizer bundle revision
5617a9f61b028005a4858fdac845db406aefb181
```

Focused M6E command covered profile/model/use-case/CLI/architecture plus the
real-bundle offline composition path before the stack was committed:

```text
67 passed in 8.30s
```

Full required matrix at the production review head:

```text
pytest tests/foundation tests/shared tests/architecture \
  tests/indexing/infrastructure/embedding -q \
  --tokenizer-assets-dir <approved-external-bundle>

1190 passed in 76.57s
```

No asset-backed test skipped. The synthetic composition test uses the real
pinned tokenizer, forbids network creation, produces at least one valid
relation, verifies deterministic repeat and aggregate-only output, and confirms
the raw file tree is byte-identical before/after.

`git diff --check`: pass for tracked changes. Independent whitespace/final-
newline check: pass for all untracked files.

## Boundary confirmation

- Jira API/PAT/network: absent.
- Output files: none.
- Raw/XHTML re-parsing in M6E: absent.
- Relation types other than `mentions_jira_key`: absent.
- Media/page-link relations: absent.
- ACL resolution or ACL mutation: absent.
- Retry/checkpoint/export/embedding: absent.
- M6F: not started.

## Review stack

```text
e336261
  -> 464869c [M6E-A] Jira relation contract, profile/model/loader, tests
     full matrix: 1,145 passed
  -> 1d9d785 [M6E-B] deterministic extraction and linkage use case, tests
     full matrix: 1,180 passed
  -> 68a4b08 [M6E-C] offline one-page acceptance CLI, tests
     full matrix: 1,190 passed
```

Production review head: `68a4b08`.

The review-summary commit contains no production behavior. M6E documentation
and state closeout remain deferred until independent approval. No patch has been
created and nothing has been pushed.
