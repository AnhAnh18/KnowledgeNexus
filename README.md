# KnowledgeNexus

KnowledgeNexus is an internal engineering knowledge platform. The repository is
currently building the Foundation data layer first: contracts, deterministic
records and snapshots, and source inventory/ingestion boundaries.

Embedding, Qdrant indexing, retrieval, chat, and presentation APIs are later
bounded contexts and are not runnable features yet.

## Requirements

- Python 3.11 or newer
- `pip`

Install the declared runtime dependencies from the repository root:

```bash
python -m pip install -r requirements.txt
```

The dependency versions are intentionally unpinned until the repository adopts
a packaging and lock-file convention. Reproducible production environments
should record the resolved versions externally in the meantime.

### Why `rfc3339-validator` is required

Foundation schemas use JSON Schema `format: date-time` fields. The
`FoundationSchemaValidator` enables `jsonschema.FormatChecker`, and
`rfc3339-validator` supplies the RFC 3339 implementation used to reject invalid
date-time values. It is therefore a runtime validation dependency, not an
optional test helper.

## Local setup

Copy the environment template and keep all real credentials local:

```bash
cp .env.example .env
```

On PowerShell:

```powershell
Copy-Item .env.example .env
```

The current Foundation code does not automatically load `.env`. Source adapters
must receive resolved connection and authentication configuration explicitly.

## Tests

Install `pytest` in the development environment if it is not already present:

```bash
python -m pip install pytest
python -m pytest tests/foundation tests/shared -q
```

The Foundation tests are offline and use synthetic or sanitized fixtures. Real
source smoke runs are separate, explicit milestone activities.

## Repository structure

```text
contracts/foundation/          Foundation schemas and integration contracts
src/knowledgenexus/foundation/ Foundation domain, application, ports, adapters
src/knowledgenexus/shared/     Shared technical contract utilities
tests/foundation/              Foundation unit and integration tests
tests/shared/                  Shared contract utility tests
data/exports/                  Published Foundation snapshots (runtime, ignored)
```

Foundation publishes snapshots under:

```text
data/exports/<dataset_name>/<dataset_version>/
```

Future indexing code must consume only published exports, never Foundation raw
or working directories.

## Current status

- M0-M4: Foundation scaffold, contracts, deterministic record builders, and
  full-snapshot export foundation complete.
- M5A: deployment-independent Confluence inventory core complete.
- M5B: deployment-specific Confluence Data Center inventory adapter is next.
- M5C: small manually reviewed real inventory follows M5B.

The current Confluence milestone is inventory metadata only. It does not fetch
page bodies, rendered HTML, comments, attachments, or permissions.

## License

Internal use.
