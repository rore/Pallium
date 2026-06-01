#!/usr/bin/env python3
"""
extensions/python/scripts/run-import-linter.py

Adapter that runs import-linter and emits boundary-violations.json matching
the schema at core/schema/boundary-violations.schema.json.

Why this exists: import-linter has no machine-readable output (no --format
flag). This script calls import-linter's create_report(...) API and walks
the resulting Report object, emitting one JSON entry per concrete violation.

Usage:
  run-import-linter.py [--config PATH] [--out PATH] [--cache-dir PATH] [--no-cache]

Exit codes:
  0 — every contract is kept
  1 — at least one contract is broken (the JSON output is still written)
  2 — script error (could not import import-linter, could not read config, etc.)

The JSON file is ALWAYS written when the script can build a report. A non-zero
exit signals violations; the file is the source of truth for the reporter.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# import-linter pinned range used by this adapter:
SUPPORTED_RANGE = ">=2.0,<3"


def _import_internals():
    """
    Import import-linter's internal modules. These are not part of the
    documented public API (which exposes only read_configuration() and
    lint_imports()), but they are used by import-linter's own CLI. The
    pinned version range tracks where they live.
    """
    try:
        from importlinter.application import use_cases  # type: ignore
        from importlinter.application.user_options import UserOptions  # noqa: F401
        from importlinter.configuration import configure  # type: ignore
        return use_cases, configure
    except ImportError as e:
        sys.stderr.write(
            f"error: could not import import-linter internals ({e}).\n"
            f"This adapter is verified against import-linter {SUPPORTED_RANGE}. "
            f"Install with: pip install 'import-linter{SUPPORTED_RANGE}'\n"
        )
        sys.exit(2)


def _safe_first_route(routes: Any) -> str:
    """Format a single chain/route from import-linter metadata into one line.

    `routes` can be a list of dicts (from layers/forbidden/independence) or a
    list of import-detail dicts (from forbidden/independence's `chains` lists).
    """
    if not isinstance(routes, list) or not routes:
        return ""
    route = routes[0]
    if isinstance(route, dict):
        # Direct edge dict: {importer, imported, ...}
        importer = route.get("importer")
        imported = route.get("imported")
        if importer and imported:
            return f"{importer} -> {imported}"
        # Layers chain dict: {chain: [...]} or {middle: [...]}
        chain = route.get("chain") or route.get("middle") or []
        if isinstance(chain, list) and chain:
            parts = []
            for hop in chain:
                if isinstance(hop, dict):
                    src = hop.get("importer") or hop.get("source")
                    dst = hop.get("imported") or hop.get("dest")
                    if src and dst:
                        parts.append(f"{src} -> {dst}")
            if parts:
                return " ; ".join(parts)
    elif isinstance(route, list):
        # Forbidden/independence: chains is a list of lists of edge dicts.
        return _safe_first_route(route)
    return ""


def _violations_from_layers(metadata: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for chains_data in metadata.get("invalid_dependencies", []) or []:
        importer = chains_data.get("importer", "?")
        imported = chains_data.get("imported", "?")
        first_route = _safe_first_route(chains_data.get("routes"))
        detail = f"{importer} is not allowed to import {imported}"
        if first_route:
            detail = f"{detail} (e.g. {first_route})"
        out.append({"detail": detail})
    for module in metadata.get("undeclared_modules", []) or []:
        out.append({"detail": f"undeclared layer module: {module}"})
    return out


def _violations_from_invalid_chains(metadata: dict[str, Any]) -> list[dict[str, str]]:
    """Used by 'forbidden' and 'independence' contracts.

    Metadata shape (per import-linter source):
      {
        "invalid_chains": [
          {
            "upstream_module": str,    # what was illegally imported
            "downstream_module": str,  # what did the importing
            "chains": [
              [ {importer, imported, line_numbers}, ... ],   # one chain
              ...
            ],
          },
          ...
        ]
      }
    """
    out: list[dict[str, str]] = []
    for chains_data in metadata.get("invalid_chains", []) or []:
        downstream = chains_data.get("downstream_module", "?")
        upstream = chains_data.get("upstream_module", "?")
        first_route = _safe_first_route(chains_data.get("chains"))
        detail = f"{downstream} is not allowed to import {upstream}"
        if first_route:
            detail = f"{detail} (e.g. {first_route})"
        out.append({"detail": detail})
    return out


def _violations_from_protected(metadata: dict[str, Any]) -> list[dict[str, str]]:
    """The 'protected' contract uses a list of BrokenContractMetadata objects
    (not plain dicts). Each has .illegal_links (list of {importer, imported,
    line_numbers}) and .top_level_module."""
    out: list[dict[str, str]] = []
    for entry in metadata.get("illegal_imports", []) or []:
        # BrokenContractMetadata-like (object with attributes) OR a dict.
        illegal_links = getattr(entry, "illegal_links", None)
        top_level = getattr(entry, "top_level_module", None)
        if illegal_links is None and isinstance(entry, dict):
            illegal_links = entry.get("illegal_links") or []
            top_level = entry.get("top_level_module") or "?"
        if illegal_links:
            for link in illegal_links:
                if isinstance(link, dict):
                    importer = link.get("importer", "?")
                    imported = link.get("imported", "?")
                    out.append({"detail": f"{importer} -> {imported} (protected: {top_level})"})
                else:
                    out.append({"detail": str(link)})
        else:
            out.append({"detail": f"protected module imported illegally: {top_level}"})
    return out


def _violations_from_acyclic(metadata: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for summary in metadata.get("summaries", []) or []:
        out.append({"detail": str(summary)})
    return out


def _violations_for_check(metadata: dict[str, Any]) -> list[dict[str, str]]:
    """
    Best-effort extractor for known import-linter contract metadata shapes.
    Falls back to stringifying the metadata dict as a single violation when
    nothing matches.
    """
    if not isinstance(metadata, dict) or not metadata:
        return [{"detail": "contract broken (no metadata available)"}]

    handled: list[dict[str, str]] = []
    if "invalid_dependencies" in metadata or "undeclared_modules" in metadata:
        handled.extend(_violations_from_layers(metadata))
    if "invalid_chains" in metadata:
        handled.extend(_violations_from_invalid_chains(metadata))
    if "illegal_imports" in metadata:
        handled.extend(_violations_from_protected(metadata))
    if "summaries" in metadata:
        handled.extend(_violations_from_acyclic(metadata))

    if handled:
        return handled

    # Fallback: surface the raw metadata so the reporter still gets a signal.
    return [{"detail": f"contract broken: {json.dumps(metadata, default=str)[:300]}"}]


def build_violations(report: Any) -> list[dict[str, str]]:
    """Walk the import-linter Report and produce json-violations entries."""
    violations: list[dict[str, str]] = []
    for contract, check in report.get_contracts_and_checks():
        if check.kept:
            continue
        for v in _violations_for_check(check.metadata):
            violations.append({
                "rule": getattr(contract, "name", "unnamed contract"),
                "detail": v["detail"],
                "severity": "error",
            })
    return violations


def write_report(out_path: Path, violations: list[dict[str, str]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "source": "import-linter",
        "violations": violations,
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Run import-linter and emit boundary-violations.json. The output "
            "format matches core/schema/boundary-violations.schema.json and is "
            "consumed by the agent-redline reporter via "
            "--boundary-format json-violations."
        ),
    )
    p.add_argument("--config", type=Path, default=None,
                   help="Path to the import-linter config file (defaults to import-linter's "
                        "search: pyproject.toml, .importlinter, setup.cfg)")
    p.add_argument("--out", type=Path, default=Path("build/import-linter-report.json"),
                   help="Where to write the JSON report (default: build/import-linter-report.json)")
    p.add_argument("--cache-dir", default=None, help="import-linter cache directory")
    p.add_argument("--no-cache", action="store_true", help="Disable import-linter caching")
    args = p.parse_args(argv)

    use_cases, configure = _import_internals()
    configure()

    # Mirror import-linter's CLI: ensure the cwd is on sys.path so the package
    # is importable in src-layout / flat-layout repos that haven't run
    # `pip install -e .`.
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    try:
        user_options = use_cases.read_user_options(
            config_filename=str(args.config) if args.config else None,
        )
        # Register built-in contract types so the report can be built.
        use_cases._register_contract_types(user_options)

        # Sentinel handling for cache_dir: import-linter uses NotSupplied to mean
        # "use the default"; None to mean "disable"; otherwise a path.
        from importlinter.application.sentinels import NotSupplied  # type: ignore
        if args.no_cache:
            cache_dir: Any = None
        elif args.cache_dir is None:
            cache_dir = NotSupplied
        else:
            cache_dir = args.cache_dir

        report = use_cases.create_report(
            user_options=user_options,
            limit_to_contracts=tuple(),
            cache_dir=cache_dir,
            show_timings=False,
            verbose=False,
        )
    except FileNotFoundError as e:
        sys.stderr.write(f"error: import-linter config not found: {e}\n")
        # Still write an empty report so downstream CI doesn't crash on missing file.
        write_report(args.out, [])
        return 2
    except Exception as e:
        sys.stderr.write(f"error: import-linter failed to build a report: {e}\n")
        write_report(args.out, [])
        return 2

    if getattr(report, "could_not_run", False):
        # Bad contract options — surface as a violation so it's visible.
        violations = []
        for contract_name, exc in report.invalid_contract_options.items():
            for field, msg in exc.errors.items():
                violations.append({
                    "rule": contract_name,
                    "detail": f"invalid contract option {field}: {msg}",
                    "severity": "error",
                })
        write_report(args.out, violations)
        sys.stderr.write(
            f"error: {len(violations)} contract(s) had invalid options; see {args.out}\n"
        )
        return 1

    violations = build_violations(report)
    write_report(args.out, violations)

    if violations:
        sys.stderr.write(
            f"import-linter: {len(violations)} violation(s); wrote {args.out}\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
