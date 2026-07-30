# One-Page Foundation Export Contract

Status: active focused contract for M6G one-page full-snapshot export.
M6G-B and later production work remain blocked until M6G-A receives an
independent approval.

Precedence: `schemas/` wins every field-level dispute. This specification sits
with the other active focused specifications and profiles above the historical
decision logs. It narrows the existing full-snapshot contract for one trusted
Confluence page; it does not change a JSON Schema.

## 1. Scope and boundary

M6G consumes one already trusted `ConfluenceAclMaterializationResult` produced
by the approved M6A-through-M6F composition. It projects and publishes that
result through the existing M3 full-snapshot path.

M6G does not recompute canonical content, chunks, Jira relations, restriction
ancestry, or ACL policy. Persistence in M6G means only a versioned Foundation
export snapshot. It does not mean SQLite metadata persistence, PostgreSQL,
Qdrant, embedding, retrieval, chat, Gauss, delta sync, tombstone detection, or
crawler checkpoint persistence.

The one-page export is fully offline. It performs no source-network request and
uses no credential.

## 2. Dataset and time identity

The exact identity is:

```text
dataset_name    = spen_knowledge_poc
source_id       = confluence_svmc_spensrv
export_mode     = full_snapshot
schemas_version = 1.0
```

`dataset_name`, `source_id`, `export_mode`, and `schemas_version` are contract
constants. They are not operator-provided values.

`generated_at` is an explicit RFC 3339 string input. It must be schema-valid,
timezone-aware, and is preserved exactly in `manifest.generated_at`.
The same validated instant is parsed to an aware `datetime` and supplied to the
existing `DatasetVersionGenerator`; no other dataset-version rule is permitted.
Equivalent offsets may therefore produce the same UTC dataset version while
retaining their explicit manifest representation. No system clock is read.

The operator supplies an export root. The dataset root is derived as:

```text
dataset_root = export_root / "spen_knowledge_poc"
```

The dataset root must already exist as a plain directory. The staging path is
derived, not independently supplied:

```text
staging_path = dataset_root / (".staging-" + dataset_version)
```

It is a direct child of the dataset root. The final version path is the direct
child `dataset_root / manifest.dataset_version`.

## 3. Trusted input and exact record projection

The input must be a trusted M6F application result, not an arbitrary collection
of record dictionaries. A public application boundary must establish that
provenance; a CLI-private helper is not a trust boundary.

Project exactly:

| Stream | Records |
|---|---|
| `documents` | one `enriched_canonical_document` |
| `chunks` | `enriched_chunks` in existing order |
| `relations` | `relations` in existing order |
| `acl` | one `acl_record` |
| `media_assets` | empty |
| `symbols` | empty |
| `sync_state` | empty |
| `tombstones` | empty |

No placeholder record may be fabricated. All eight JSONL files exist even when
their stream is empty.

Projection preserves record order and does not mutate the result or any nested
record. Because the result owns mutable nested JSON values, implementation must
take an ownership-isolated projection snapshot and verify the trusted input is
unchanged.

## 4. Projection and graph invariants

All projected records pass their active Foundation schemas before staging.
Schema validity alone is insufficient; the following also hold:

- there is exactly one CanonicalDocument and exactly one ACLRecord;
- the canonical `source_system` is `confluence`;
- the canonical `source_type` is `wiki_page`;
- the canonical `space_key` is exactly `SVMC`;
- the canonical `page_id` is a valid Confluence page identity;
- `acl_record.source_system == "confluence"`;
- `acl_record.document_id == canonical.document_id`;
- `acl_record.acl_id == canonical.acl_id`;
- every chunk `document_id` equals the canonical `document_id`;
- every chunk `source_system`, `source_type`, `space_key`, and `page_id` equal
  the canonical values;
- every chunk `acl_tags` exactly equals `acl_record.acl_tags`;
- chunk IDs are unique;
- relation IDs are unique;
- canonical `relation_ids` exactly equals the exported relation IDs in export
  order;
- every exported relation `source_id` equals the canonical `document_id`;
- every relation ID referenced by a chunk resolves to an exported relation;
- chunk and relation order exactly preserves the trusted M6F result;
- manifest counts exactly equal records actually emitted in all eight streams.

The checks above are export-boundary checks, not recomputation of M6F policy.
Any failure is `export_projection`. A page outside the locked SVMC source must
not be exported under `confluence_svmc_spensrv`.

No raw page, restriction sidecar, tokenizer asset, normalized body, local path,
or source URL is copied into Manifest metadata.

## 5. Source scopes

The exact Manifest shape is:

```json
{
  "confluence": {
    "source_ids": ["confluence_svmc_spensrv"],
    "space_keys": ["<canonical space_key>"],
    "page_ids": ["<canonical page_id>"]
  }
}
```

`source_ids` contains the contract constant, not a value read from the
CanonicalDocument. `space_keys` and `page_ids` contain the already validated
canonical values. Array and object-key order are deterministic. No URL or
filesystem path is allowed.

## 6. Profile provenance and config hash

An arbitrary operator-provided `config_hash` is forbidden. The exact two
profile files used by the composition/export run are the config-hash source.
Profile text and loaded profile objects must not come from independent inputs.
Implementation must prevent a verify/load mismatch and must not use an implicit
cache.

For each profile:

1. read its exact bytes from the explicit path;
2. decode with strict UTF-8;
3. apply `TextNormalizationRules.normalize_text`;
4. validate/load the profile represented by those same bytes;
5. use the normalized string below.

The canonical hash input is:

```json
{
  "contract_version": "one-page-export-v1",
  "dataset_name": "spen_knowledge_poc",
  "source_id": "confluence_svmc_spensrv",
  "embedding_profile_text": "<normalized embedding profile text>",
  "jira_relation_profile_text": "<normalized Jira profile text>"
}
```

Serialize with:

```text
sort_keys=True
ensure_ascii=False
separators=(",", ":")
allow_nan=False
```

`config_hash` is lowercase SHA-256 of the canonical JSON UTF-8 bytes.
`chunker_version` comes from the loaded embedding profile and must also equal
every exported chunk's `chunker_version`; it is not separately hard-coded.

## 7. Required M3 reuse

Implementation uses the existing:

- `FullSnapshotStagingWriter`;
- `FullSnapshotStagingCompleter`;
- `FullSnapshotPublisher`;
- `DatasetVersionGenerator`.

A parallel JSONL writer, snapshot completer, publisher, pointer writer, or
dataset-version generator is forbidden.

The existing owned-staging cleanup behavior remains valid. M6G adds no
overwrite, recovery, implicit retry, copy fallback, post-publication rollback,
or automatic repair. A pre-existing staging path, final version path, or unsafe
pointer state fails closed under the existing M3 rules.

## 8. Reusable composition boundary

M6G must not import private functions, private dataclasses, or other private
state from the M6F-C2 CLI. The trusted M6A-through-M6F composition must be
exposed through a reusable application boundary.

Refactoring the existing C2 CLI to call that boundary must preserve its
arguments, sanitized output, exit mappings 1 through 13, deterministic repeat,
no-network behavior, and acceptance invariants. This contract locks behavior,
not a speculative public class or function signature.

## 9. Deterministic quality report

M6G extends the existing M3 report through a backward-compatible extension of
`FullSnapshotStagingCompleter`. It must not write a competing report before or
after the completer. Calling the completer without M6G quality input preserves
the existing M3 report behavior and golden output.

The extended report uses these sections in this order:

1. Snapshot;
2. Active Profiles;
3. Record Counts;
4. Jira Relation Quality;
5. ACL Quality;
6. Empty and Deferred Streams;
7. Completion Checks;
8. Publication State;
9. Scope.

Within a section, fixed fields use contract order. Jira candidate/key
collections retain the trusted M6E source-first order. ACL reason codes retain
the locked M6F policy order. Counts are decimal integers; booleans are lowercase
`true` or `false`.

The report includes:

- active profile, profile status, and chunker version;
- all eight stream counts;
- the existing Jira relation quality observation and aggregate metrics;
- the ACL aggregate quality observation, aggregate metrics, and reason codes;
- default-deny and manual-review aggregate status;
- explicit empty/deferred declarations for media, symbols, sync state, and
  tombstones;
- schema, count, machine-file-set, and completion checks.

The report is completed before publication. It must therefore state
`PENDING_AT_REPORT_COMPLETION` for post-publication verification; it must never
claim that final-directory or `LATEST.txt` checks have already passed.
Post-publication checks belong to the external acceptance gate and the report
is not mutated after publication.

The report excludes ACL tags, principals, crawler identity, raw or normalized
body content, local paths, and internal URLs. Real source-derived Jira quality
details may exist only in the local ignored export artifact. Git review and
closeout evidence remains aggregate-only.

## 10. Failure semantics

The future M6G command preserves M6F-C2 exit mappings 1 through 13 and reserves:

```text
14 export_configuration
15 export_projection
16 export_staging
17 export_completion
18 export_publication
19 export_acceptance
```

Configuration covers dataset/profile/time/path input. Projection covers trusted
result and cross-record failures. Staging, completion, and publication map only
their corresponding M3 stages. Acceptance covers post-publication verification.

Output is deterministic and sanitized. Arbitrary exception text, record values,
identities, paths, URLs, principals, ACL tags, content, and hashes are forbidden
from stdout and stderr.

### 10.1. Configuration failure observability (M6G-D-O1)

Exit code 14 (`export_configuration`) carries structured `stage` and `cause_family`
metadata. The vocabularies below are locked; no additional values are permitted.

**Stage vocabulary (11 values):**

```text
embedding_profile_read
embedding_profile_decode
embedding_profile_parse
jira_profile_read
jira_profile_decode
jira_profile_parse
profile_bundle_construction
export_input_validation
generated_at_validation
dataset_root_validation
dataset_version_generation
```

**Cause family vocabulary (6 values):**

```text
io_error
text_decode_error
profile_validation_error
type_error
value_error
unexpected_error
```

**CLI projection for exit 14:** When the CLI exits with code 14, it writes to
stderr a single JSON object with exactly these keys:

```json
{
  "status": "failed",
  "category": "export_configuration",
  "stage": "<one of 11 stage values>",
  "cause_family": "<one of 6 cause_family values>"
}
```

No other fields, paths, identities, or exception text are permitted in the
output. This structured metadata enables automated diagnosis without leaking
secrets or internal state.

`stage` and `cause_family` are closed, allowlisted semantic values drawn only
from the two vocabularies above. They are never derived from, and never
contain, raw exception text, exception type names, tracebacks, or any runtime
value (paths, identifiers, profile fragments, environment values). `status`
and `category` remain exactly as defined in §10 and stay wire-compatible with
existing M6G-C consumers that only read those two fields. Successful CLI
output and all non-configuration failure categories (exit codes other than 14)
are unchanged by this section. This section introduces no change to any
Foundation JSON Schema (`schemas/*.json`); `stage` and `cause_family` are CLI
stderr-projection fields only.

## 11. Acceptance gates

The gates are separate:

1. synthetic implementation and code review;
2. source-review to main-transfer scoped tree equivalence;
3. frozen main-machine execution commit;
4. one real offline full-snapshot export;
5. independent review of sanitized real-run evidence;
6. documentation closeout.

Cross-repository SHAs use the roles in
`.local_ai/REPOSITORY_TRANSFER_POLICY.md`. A `SOURCE_REVIEW_HEAD` is provenance
only and is never a mandatory checkout target in the main-machine repository.
The main repository creates its own `MAIN_TRANSFER_HEAD` and
`MAIN_EXECUTION_HEAD`; equality is proven over the explicit transferred file
set, not by comparing commit identities.

The real run verifies:

- no network or credentials;
- tracked worktree clean before execution and unchanged afterward;
- final version directory exists;
- `manifest.dataset_version` equals its directory name;
- exactly ten expected files exist inside the version directory: eight JSONL
  streams, `manifest.json`, and `quality_report.md`;
- every JSONL record validates;
- Manifest validates and all eight counts match;
- record graph and ACL invariants in section 4 hold;
- all deferred stream files are empty;
- dataset-root `LATEST.txt` points to the published version;
- raw page and restriction sidecar remain byte-identical;
- the real export remains ignored and uncommitted.

The immutable snapshot report may retain its pre-publication state declaration.
The sanitized acceptance evidence records the actual publication checks.

## 12. Security and durable evidence

Real raw data, the external restriction sidecar, tokenizer assets, and the
export snapshot remain outside Git history.

Durable review evidence must not contain secrets, internal URLs, local paths,
real source IDs or page IDs, principals, ACL tags, source content, exact real
timestamps, exact artifact sizes, detailed observation distributions, or full
artifact hashes. Short repository-role commit references and aggregate
booleans/count-test results are allowed.

The local ignored export may contain schema-required source identifiers and
the bounded quality details defined in section 9. It is not copied into Git
review evidence.

## 13. Staging and exclusions

M6G is decomposed directionally:

- **M6G-A:** this focused contract and navigation/state synchronization;
- **M6G-B:** reusable composition boundary plus pure export projection and
  configuration derivation;
- **M6G-C:** M3 staging/completion/publication composition, offline CLI, and
  synthetic acceptance tests;
- **M6G-D:** real offline export evidence review and documentation closeout.

This decomposition does not authorize later stages before the preceding
approval gate.

Out of scope are delta export, tombstone production, sync-state/checkpoint
persistence, media and symbol production, SQLite/PostgreSQL, Indexing, Qdrant,
embedding, retrieval, chat, Gauss, M7, and unrelated refactoring.