"""Runner and result builder.

Selection rules:

- A mandatory check runs in every profile. The manifest cannot disable it.
- Another check runs when the manifest enables it and the profile is not `quick`.
- A check with status `required` that does not run in profile `ci` or `full`
  has status `skipped` and fails the run.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from deterministic_controls import __version__
from deterministic_controls.core.api import Context, Finding
from deterministic_controls.core.catalog import CatalogEntry
from deterministic_controls.core.errors import (
    EXIT_CONFIG,
    EXIT_DEFECTS,
    EXIT_INTERNAL,
    EXIT_PASS,
    ConfigError,
)
from deterministic_controls.core.manifest import Manifest
from deterministic_controls.core.policy import finding_fails

RESULT_SCHEMA_VERSION = 1


def validate_manifest(manifest: Manifest, catalog: dict[str, CatalogEntry]) -> None:
    """Raise ConfigError if the manifest does not fit the catalog."""
    for key, ids in (("enabled", manifest.enabled), ("disabled", manifest.disabled)):
        for check_id in ids:
            if check_id not in catalog:
                raise ConfigError(f"manifest '{key}' has unknown check ID: {check_id}")
    for check_id in manifest.disabled:
        if catalog[check_id].mandatory:
            raise ConfigError(f"check {check_id} is mandatory and cannot be disabled")
    for check_id, params in manifest.parameters.items():
        if check_id not in catalog:
            raise ConfigError(f"manifest parameters name unknown check ID: {check_id}")
        unknown = sorted(set(params) - set(catalog[check_id].parameters))
        if unknown:
            raise ConfigError(
                f"manifest has unknown parameters for {check_id}: {', '.join(unknown)}"
            )


def _digest(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _repository_revision(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    rev = out.stdout.strip()
    return rev if out.returncode == 0 and rev else "unknown"


def _selected(manifest: Manifest, catalog: dict[str, CatalogEntry]) -> list[tuple[CatalogEntry, str | None]]:
    """Return (entry, skip_reason) for each check that appears in the result."""
    chosen = []
    for check_id in sorted(catalog):
        entry = catalog[check_id]
        enabled = check_id in manifest.enabled
        if entry.mandatory:
            chosen.append((entry, None))
        elif manifest.profile == "quick":
            if enabled or entry.status == "required":
                chosen.append((entry, "not run in profile quick"))
        elif enabled:
            chosen.append((entry, None))
        elif entry.status == "required":
            chosen.append((entry, "required check is not enabled in the manifest"))
    return chosen


def _run_one(entry: CatalogEntry, context: Context) -> tuple[str, list[Finding], str | None]:
    try:
        module = importlib.import_module(entry.module)
        function = getattr(module, entry.entry)
        findings = function(context)
        if not isinstance(findings, list) or not all(isinstance(f, Finding) for f in findings):
            raise TypeError("check must return a list of Finding")
    except Exception as exc:  # noqa: BLE001 - a crash must become status "error"
        return "error", [], f"{type(exc).__name__}: {exc}"
    findings = sorted(findings, key=Finding.sort_key)
    failed = any(finding_fails(f) for f in findings)
    return ("failed" if failed else "passed"), findings, None


def run_checks(
    root: Path,
    manifest: Manifest,
    manifest_text: str,
    catalog: dict[str, CatalogEntry],
) -> dict[str, Any]:
    """Run the selected checks. Return the result dictionary."""
    validate_manifest(manifest, catalog)
    root = Path(root).resolve()
    checks = []
    for entry, skip_reason in _selected(manifest, catalog):
        started = time.monotonic()
        findings: list[Finding] = []
        reason = skip_reason
        if skip_reason is not None:
            status = "skipped"
        else:
            params = {**entry.parameters, **manifest.parameters.get(entry.id, {})}
            status, findings, reason = _run_one(entry, Context(root, params))
        item: dict[str, Any] = {
            "check_id": entry.id,
            "status": status,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "findings": [f.to_dict() for f in findings],
        }
        if reason is not None:
            item["reason"] = reason
        checks.append(item)
    return build_result(root, manifest, manifest_text, catalog, checks)


def _required_skipped(item: dict, catalog: dict[str, CatalogEntry]) -> bool:
    return item["status"] == "skipped" and catalog[item["check_id"]].status == "required" and (
        item.get("reason") != "not run in profile quick"
    )


def build_result(
    root: Path,
    manifest: Manifest,
    manifest_text: str,
    catalog: dict[str, CatalogEntry],
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    checks = sorted(checks, key=lambda c: c["check_id"])
    if any(c["status"] == "error" for c in checks):
        status = "error"
    elif any(c["status"] == "failed" or _required_skipped(c, catalog) for c in checks):
        status = "failed"
    else:
        status = "passed"
    catalog_state = {
        k: [e.version, e.status, e.severity, e.module, e.entry, e.mandatory]
        for k, e in sorted(catalog.items())
    }
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "tool_version": __version__,
        "repository_revision": _repository_revision(root),
        "control_revision": _digest(catalog_state)[:16],
        "config_digest": hashlib.sha256(manifest_text.encode("utf-8")).hexdigest(),
        "profile": manifest.profile,
        "status": status,
        "checks": checks,
    }


def exit_code(result: dict[str, Any]) -> int:
    return {"passed": EXIT_PASS, "failed": EXIT_DEFECTS, "error": EXIT_INTERNAL}[result["status"]]


__all__ = ["run_checks", "build_result", "exit_code", "validate_manifest", "EXIT_CONFIG"]
