"""Command line interface: list, check, explain, version, adopt."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from deterministic_controls import __version__
from deterministic_controls.core.catalog import load_catalog
from deterministic_controls.core.errors import (
    EXIT_CONFIG,
    EXIT_INTERNAL,
    EXIT_PASS,
    ConfigError,
)
from deterministic_controls.core.manifest import PROFILES, read_manifest
from deterministic_controls.core.runner import exit_code, run_checks


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse exits 2 by default. Keep it explicit.
        self.print_usage(sys.stderr)
        self.exit(EXIT_CONFIG, f"{self.prog}: error: {message}\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="deterministic_controls")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    sub.add_parser("list", help="list the checks of the catalog")
    sub.add_parser("version", help="print the tool version")
    explain = sub.add_parser("explain", help="explain one check")
    explain.add_argument("check_id")
    check = sub.add_parser("check", help="run the checks")
    check.add_argument("--root", default=".")
    check.add_argument("--profile", choices=PROFILES, default=None)
    check.add_argument("--format", choices=("text", "json"), default="text")
    check.add_argument("--report", default=None, metavar="FILE")
    sub.add_parser("adopt", help="adoption tools", add_help=False)
    return parser


def _cmd_list(catalog) -> int:
    for entry in catalog.values():
        flag = " mandatory" if entry.mandatory else ""
        print(f"{entry.id}\t{entry.status}{flag}\t{entry.summary}")
    return EXIT_PASS


def _cmd_explain(catalog, check_id: str) -> int:
    if check_id not in catalog:
        raise ConfigError(f"unknown check ID: {check_id}")
    e = catalog[check_id]
    print(f"id: {e.id}")
    print(f"summary: {e.summary}")
    print(f"version: {e.version}")
    print(f"status: {e.status}")
    print(f"severity: {e.severity}")
    print(f"mandatory: {str(e.mandatory).lower()}")
    print(f"module: {e.module}")
    print(f"entry: {e.entry}")
    for key in sorted(e.parameters):
        print(f"parameter: {key} = {json.dumps(e.parameters[key])}")
    return EXIT_PASS


def _format_text(result: dict) -> str:
    lines = [f"profile: {result['profile']}  status: {result['status']}"]
    for check in result["checks"]:
        suffix = f" ({check['reason']})" if "reason" in check else ""
        lines.append(f"{check['check_id']}: {check['status']}{suffix}")
        for f in check["findings"]:
            where = f["path"] or "-"
            if f["line"] is not None:
                where += f":{f['line']}"
            lines.append(f"  [{f['severity']}] {f['rule_id']} {where} {f['message']}")
    return "\n".join(lines)


def _cmd_check(args, catalog) -> int:
    root = Path(args.root).resolve()
    if not root.is_dir():
        raise ConfigError(f"root is not a directory: {root}")
    report = None
    if args.report:
        report = Path(args.report).resolve()
        if report == root or root in report.parents:
            raise ConfigError("the report file must be outside the checked repository")
    manifest, text = read_manifest(root)
    if args.profile:
        manifest = type(manifest)(
            profile=args.profile,
            enabled=manifest.enabled,
            disabled=manifest.disabled,
            parameters=manifest.parameters,
        )
    result = run_checks(root, manifest, text, catalog)
    as_json = json.dumps(result, indent=2, sort_keys=True)
    print(as_json if args.format == "json" else _format_text(result))
    if report is not None:
        report.write_text(as_json + "\n", encoding="utf-8")
    return exit_code(result)


def _cmd_adopt(argv: list[str]) -> int:
    try:
        module = importlib.import_module("deterministic_controls.adopt")
    except ModuleNotFoundError as exc:
        if exc.name != "deterministic_controls.adopt":
            raise
        print("adopt: not implemented", file=sys.stderr)
        return EXIT_CONFIG
    return int(module.main(argv))


def main(argv: list[str] | None = None, *, catalog_dir: Path | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "adopt":
        return _cmd_adopt(argv[1:])
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_CONFIG
    try:
        if args.command == "version":
            print(__version__)
            return EXIT_PASS
        catalog = load_catalog(catalog_dir)
        if args.command == "list":
            return _cmd_list(catalog)
        if args.command == "explain":
            return _cmd_explain(catalog, args.check_id)
        return _cmd_check(args, catalog)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except Exception as exc:  # noqa: BLE001 - a crash never gives 0
        print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INTERNAL
