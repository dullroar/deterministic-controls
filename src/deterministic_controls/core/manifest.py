"""Manifest reader. The manifest is `controls.toml` with `schema_version = 1`."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deterministic_controls.core.errors import ConfigError

MANIFEST_NAME = "controls.toml"
SCHEMA_VERSION = 1
PROFILES = ("quick", "ci", "full")
_KEYS = {"schema_version", "profile", "enabled", "disabled", "parameters"}


@dataclass(frozen=True)
class Manifest:
    profile: str = "ci"
    enabled: tuple[str, ...] = ()
    disabled: tuple[str, ...] = ()
    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)


def _id_list(data: dict, key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"manifest key '{key}' must be a list of strings")
    return tuple(value)


def parse_manifest(text: str) -> Manifest:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"manifest is not valid TOML: {exc}") from exc
    unknown = sorted(set(data) - _KEYS)
    if unknown:
        raise ConfigError(f"manifest has unknown keys: {', '.join(unknown)}")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ConfigError(
            f"manifest schema_version must be {SCHEMA_VERSION}, "
            f"found {data.get('schema_version')!r}"
        )
    profile = data.get("profile", "ci")
    if profile not in PROFILES:
        raise ConfigError(f"manifest profile must be one of {', '.join(PROFILES)}")
    parameters = data.get("parameters", {})
    if not isinstance(parameters, dict) or not all(
        isinstance(v, dict) for v in parameters.values()
    ):
        raise ConfigError("manifest key 'parameters' must be a table of tables")
    return Manifest(
        profile=profile,
        enabled=_id_list(data, "enabled"),
        disabled=_id_list(data, "disabled"),
        parameters=parameters,
    )


def read_manifest(root: Path) -> tuple[Manifest, str]:
    """Read the manifest of a repository. Return it with its raw text."""
    path = Path(root) / MANIFEST_NAME
    if not path.is_file():
        raise ConfigError(f"manifest not found: {path}")
    text = path.read_text(encoding="utf-8")
    return parse_manifest(text), text
