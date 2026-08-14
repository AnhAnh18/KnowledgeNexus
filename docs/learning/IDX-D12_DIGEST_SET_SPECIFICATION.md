# IDX-C1 Digest-Set Specification

Status: **specified; implementation not authorized**

This is the byte-level Phase A specification for D12's digest-set. It does not
modify Foundation code or schemas and does not authorize IDX-C1 implementation.

## File and encoding

- Exact filename: `digest-set.json`.
- It is a regular UTF-8 file without a BOM, encoded as one JSON object followed
  by exactly one LF (`\n`). CRLF is not valid for the published bytes.
- JSON is serialized with sorted object keys, no insignificant whitespace,
  UTF-8 escaped only as required by JSON, and `allow_nan=false`.
- The member array order below is normative and is not derived from directory
  enumeration.

## Object shape

The top-level object contains exactly these fields:

```json
{"dataset_version":"<manifest.dataset_version>","members":[{"byte_size":0,"filename":"manifest.json","sha256":"<64 lowercase hex>"}],"schema_version":"1.0"}
```

`schema_version` is the digest-set contract version. `dataset_version` is copied
byte-for-byte from `manifest.json.dataset_version` and must equal the version
directory and bound trigger version. `members` is a non-empty array. Each
member object contains exactly `filename`, `byte_size`, and `sha256`;
`byte_size` is a non-negative integer and `sha256` is lowercase 64-character
SHA-256 hex. No duplicate filenames are allowed.

No new `dataset_name` field is invented here; dataset identity remains governed
by the approved D12 contract form.

## Member order and set rule

For the current schema-version allowance, `members` must appear in this exact
order:

1. `manifest.json`
2. `documents.jsonl`
3. `chunks.jsonl`
4. `relations.jsonl`
5. `acl.jsonl`
6. `media_assets.jsonl`
7. `symbols.jsonl`
8. `sync_state.jsonl`
9. `tombstones.jsonl`
10. `quality_report.md`

The published directory must contain exactly the ten listed members plus
`digest-set.json`. The digest-set does not list or hash itself. A future
structure stream may be added only by a schema-version-keyed allowed-name set;
the resolver must validate membership from the digest-set rather than a
hard-coded file count.

## Integrity and publication timing

For each listed member, `byte_size` and `sha256` are computed from the exact
bytes that will be published. The digest-set is written after the existing ten
complete files have been written and validated, while still in staging, and
before the staging directory is atomically renamed. It is never added to an
already published version directory.

`manifest_sha256` is SHA-256 of the exact `manifest.json` bytes. To preserve the
control-plane binding, `digest_set_sha256` is SHA-256 of the exact
`digest-set.json` bytes. An event/trigger carries both lowercase digests with
the exact dataset/version and immutable location; it carries no content,
credentials, local paths, or source identifiers. Indexing verifies both control
plane digests before parsing either file, then verifies every member's size and
digest before any record parsing or storage mutation.

## Foundation gate consequences

- `EXPECTED_MACHINE_FILES` remains the current nine-file staging gate: the
  manifest plus eight JSONL streams.
- `EXPECTED_COMPLETE_FILES` becomes the eleven-file gate: the nine machine
  files, `quality_report.md`, and `digest-set.json`.
- The publisher exact-file gate also becomes eleven files.
- No published version may be replaced or amended to add the digest-set.
