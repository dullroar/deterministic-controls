"""Catalog loader. It reads `catalog/*.toml`. It never imports a check module."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deterministic_controls.core.api import SEVERITIES
from deterministic_controls.core.errors import ConfigError

STATUSES = ("experimental", "advisory", "required", "deprecated")
_REQUIRED = ("id", "summary", "version", "status", "severity", "module", "entry")
_KEYS = set(_REQUIRED) | {"parameters", "mandatory"}


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    summary: str
    version: str
    status: str
    severity: str
    module: str
    entry: str
    parameters: dict[str, Any] = field(default_factory=dict)
    mandatory: bool = False


def default_catalog_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "catalog"


def _parse_entry(path: Path) -> CatalogEntry:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"catalog file {path.name} is not valid TOML: {exc}") from exc
    missing = [k for k in _REQUIRED if k not in data]
    if missing:
        raise ConfigError(f"catalog file {path.name} lacks keys: {', '.join(missing)}")
    unknown = sorted(set(data) - _KEYS)
    if unknown:
        raise ConfigError(f"catalog file {path.name} has unknown keys: {', '.join(unknown)}")
    if data["id"] != path.stem:
        raise ConfigError(f"catalog file {path.name} must hold id '{path.stem}'")
    if data["status"] not in STATUSES:
        raise ConfigError(f"catalog file {path.name} has bad status {data['status']!r}")
    if data["severity"] not in SEVERITIES:
        raise ConfigError(f"catalog file {path.name} has bad severity {data['severity']!r}")
    mandatory = data.get("mandatory", False)
    if not isinstance(mandatory, bool):
        raise ConfigError(f"catalog file {path.name}: 'mandatory' must be a boolean")
    parameters = data.get("parameters", {})
    if not isinstance(parameters, dict):
        raise ConfigError(f"catalog file {path.name}: 'parameters' must be a table")
    return CatalogEntry(
        id=data["id"],
        summary=str(data["summary"]),
        version=str(data["version"]),
        status=data["status"],
        severity=data["severity"],
        module=str(data["module"]),
        entry=str(data["entry"]),
        parameters=parameters,
        mandatory=mandatory,
    )


def load_catalog(directory: Path | None = None) -> dict[str, CatalogEntry]:
    """Load all catalog files of a directory. Return entries sorted by ID."""
    directory = Path(directory) if directory else default_catalog_dir()
    if not directory.is_dir():
        raise ConfigError(f"catalog directory not found: {directory}")
    entries = [_parse_entry(p) for p in sorted(directory.glob("*.toml"))]
    return {e.id: e for e in entries}
