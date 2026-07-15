# schemas/

Normative output contract for the AI Knowledge Platform — Part 1 (Knowledge Foundation), v7.1.

These JSON Schema (draft 2020-12) files are the **authoritative** definitions of every record written to the export. The JSON blocks in `AI_Knowledge_Platform_Master_Spec_v7_1.md` are illustrative; where an example and a schema disagree, the schema wins and the example must be corrected.

## Files

| Schema | Record | JSONL file | Spec section |
|---|---|---|---|
| `defs.schema.json` | Shared ID grammars, enums, timestamp format | — | §16.1 |
| `canonical_document.schema.json` | CanonicalDocument | documents.jsonl | Appendix A |
| `chunk_record.schema.json` | ChunkRecord | chunks.jsonl | §16.3 |
| `relation_record.schema.json` | RelationRecord | relations.jsonl | §13 |
| `acl_record.schema.json` | ACLRecord | acl.jsonl | §14 |
| `media_asset.schema.json` | MediaAsset | media_assets.jsonl | §11 |
| `symbol_record.schema.json` | SymbolRecord | symbols.jsonl | §12 |
| `sync_state_record.schema.json` | SyncStateRecord (snapshot) | sync_state.jsonl | Appendix A |
| `tombstone_record.schema.json` | TombstoneRecord | tombstones.jsonl | §16.2 |
| `manifest.schema.json` | Manifest | manifest.json | §16.2, Appendix A |

## Binding rules (master spec §16.1)

1. Every record in every JSONL file carries `schema_version` (currently `"1.0"`).
2. **Exporters MUST validate each record against its schema before writing.** A validation failure fails the export run (acceptance criterion "Schema validation", §19).
3. Unknown top-level fields are rejected (`additionalProperties: false`) everywhere except inside explicitly free-form `metadata` objects.
4. `acl_tags` is never empty (`minItems: 1`); the default-deny value is `["restricted:unresolved"]` (§14.3).

## Cross-file references

Record schemas `$ref` shared definitions in `defs.schema.json` by absolute `$id`
(`https://svmc.samsung/knowledge/schemas/…`). `defs.schema.json` is the single source of
truth for ID grammars and enums, so the record schemas cannot drift from each other. A
validator must load all files into one registry, for example:

```python
import glob, json, os
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

resources = []
for path in glob.glob("schemas/*.json"):
    doc = json.load(open(path))
    resources.append((doc["$id"], Resource.from_contents(doc)))
registry = Registry().with_resources(resources)

schema = json.load(open("schemas/chunk_record.schema.json"))
Draft202012Validator(schema, registry=registry).validate(record)
```

## Evolution policy

- **Minor** (`1.0` → `1.1`): additive changes only — new optional fields, new enum values, widened patterns. Consumers on the older minor keep working, and every export ships the exact schema set it was produced with (`manifest.schemas_version`), so consumers never guess.
- **Major** (`1.x` → `2.0`): any breaking change (field removed/renamed, type narrowed, new required field, enum value removed). A major bump requires a fresh `full_snapshot` export (§16.2) and a bump of `manifest.schemas_version`.
- `manifest.schemas_version` records the schema-set version used to produce an export so Task 2 can detect a contract change.

## Change notes

- 2026-07-03: `aclTag` pattern gains `repo:{name}` for git-source chunks (v7.2 D4). Applied in place within schema_version 1.0 — no export existed yet, so there was no compatibility surface and no version bump was required.
