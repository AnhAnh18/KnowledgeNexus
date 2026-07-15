"""Load Foundation JSON Schemas from the in-repo contract root."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from knowledgenexus.shared.errors import ContractLoadError, ContractSchemaNotFoundError


DEFAULT_SCHEMA_DIR = Path("contracts") / "foundation" / "schemas"


@dataclass(frozen=True)
class FoundationContractSchemas:
    """Loaded Foundation schema documents and lookup indexes."""

    schema_dir: Path
    schemas_by_id: Mapping[str, Mapping[str, Any]]
    schemas_by_name: Mapping[str, Mapping[str, Any]]
    schema_paths_by_name: Mapping[str, Path]

    def get_schema(self, schema_name: str) -> Mapping[str, Any]:
        try:
            return self.schemas_by_name[schema_name]
        except KeyError as exc:
            available = ", ".join(sorted(self.schemas_by_name))
            raise ContractSchemaNotFoundError(
                f"Unknown Foundation schema '{schema_name}'. Available schemas: {available}"
            ) from exc

    def get_schema_path(self, schema_name: str) -> Path | None:
        return self.schema_paths_by_name.get(schema_name)


def default_contract_root(start: Path | None = None) -> Path:
    """Find the repository contract root, preferring the current workspace."""

    search_start = (start or Path.cwd()).resolve()
    candidates = [search_start, *search_start.parents]

    for candidate in candidates:
        contract_root = candidate / "contracts" / "foundation"
        if (contract_root / "schemas").is_dir():
            return contract_root

    package_root = Path(__file__).resolve()
    for candidate in package_root.parents:
        contract_root = candidate / "contracts" / "foundation"
        if (contract_root / "schemas").is_dir():
            return contract_root

    return Path("contracts") / "foundation"


def load_foundation_contract_schemas(
    contract_root: str | Path | None = None,
    schema_dir: str | Path | None = None,
) -> FoundationContractSchemas:
    """Load every ``*.json`` schema from ``contracts/foundation/schemas``.

    Schemas are indexed by ``$id`` when present. Convenience names are also
    registered from schema metadata so callers can use names like
    ``ChunkRecord`` without depending on a file naming convention.
    """

    resolved_schema_dir = _resolve_schema_dir(contract_root, schema_dir)
    if not resolved_schema_dir.is_dir():
        raise ContractLoadError(
            f"Foundation schema directory does not exist: {resolved_schema_dir}"
        )

    schema_paths = sorted(resolved_schema_dir.glob("*.json"))
    if not schema_paths:
        raise ContractLoadError(
            f"No Foundation schema files found in {resolved_schema_dir}"
        )

    schemas_by_id: dict[str, Mapping[str, Any]] = {}
    schemas_by_name: dict[str, Mapping[str, Any]] = {}
    schema_paths_by_name: dict[str, Path] = {}

    for schema_path in schema_paths:
        schema = _read_schema(schema_path)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            schemas_by_id[schema_id] = schema

        for name in _schema_names(schema_path, schema):
            schemas_by_name[name] = schema
            schema_paths_by_name[name] = schema_path

    return FoundationContractSchemas(
        schema_dir=resolved_schema_dir,
        schemas_by_id=MappingProxyType(schemas_by_id),
        schemas_by_name=MappingProxyType(schemas_by_name),
        schema_paths_by_name=MappingProxyType(schema_paths_by_name),
    )


def _resolve_schema_dir(
    contract_root: str | Path | None,
    schema_dir: str | Path | None,
) -> Path:
    if schema_dir is not None:
        return Path(schema_dir).resolve()

    root = Path(contract_root).resolve() if contract_root is not None else default_contract_root()
    return (root / "schemas").resolve()


def _read_schema(schema_path: Path) -> Mapping[str, Any]:
    try:
        loaded = json.loads(schema_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractLoadError(
            f"Invalid JSON schema file {schema_path}: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    if not isinstance(loaded, dict):
        raise ContractLoadError(
            f"Schema file must contain a JSON object: {schema_path}"
        )

    return loaded


def _schema_names(schema_path: Path, schema: Mapping[str, Any]) -> set[str]:
    names = {schema_path.name, schema_path.stem}

    schema_id = schema.get("$id")
    if isinstance(schema_id, str) and schema_id:
        id_name = schema_id.rsplit("/", 1)[-1]
        names.add(schema_id)
        names.add(id_name)
        names.add(Path(id_name).stem)

    title = schema.get("title")
    if isinstance(title, str) and title:
        names.add(title)

    return names


load_contract_schemas = load_foundation_contract_schemas
