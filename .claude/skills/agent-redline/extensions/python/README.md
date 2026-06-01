# python — agent-redline language extension

The reference language extension for **Python services and packages** using **import-linter** as the boundary-rule backend.

## When to pick this extension

Use this extension if your repo is:

- A Python web service (FastAPI, Flask, Django, Starlette, aiohttp, Litestar, or plain WSGI)
- A pip-installable Python library or package
- Built with `pyproject.toml` (PEP 621), `setup.py`, or `setup.cfg`
- Organized in a layered, hexagonal, or feature-sliced layout
- (Optional) using Alembic / Django / yoyo / custom migrations
- (Optional) using Django REST Framework, FastAPI dependencies, Flask-Login

The extension covers three Python shapes:

1. **Layered service** — services with API/domain/adapters layers, including Django (with addendum).
2. **Library / package** — pip-installable packages whose value is their public API.
3. **Zone-only fallback** — pipelines (Airflow / Prefect / Dagster), notebook-heavy ML repos, monorepos with mixed shapes. Boundary enforcement is skipped; zone classification, persistence, security, and PR-size checks still run.

`profile.md` enumerates the three shapes; bootstrap inspects the repo, picks one (or proposes two when ambiguous), and the developer confirms.

## What's inside

| File | What it is |
|---|---|
| `README.md` | This file. |
| `profile.md` | Default zones, boundary rules, and Python-specific gotchas — broken into the three shapes. The agent reads this during bootstrap to draft `agent-policy.yaml`. |
| `scaffold.md` | How the agent installs `import-linter`, generates the contracts, and wires CI. |
| `operating.md` | Stack-specific operating-mode notes. |
| `adapter.yaml` | Tells the reporter the boundary-rule backend emits `json-violations` (see `core/schema/boundary-violations.schema.json`). |
| `scripts/run-import-linter.py` | Adapter that runs `import-linter` and emits the `json-violations` report. Necessary because `import-linter` has no built-in machine-readable output. |

## Why import-linter

[import-linter](https://github.com/seddonym/import-linter) is the most mature Python tool for layered architecture and forbidden-import contracts. It builds a static import graph (via [grimp](https://github.com/seddonym/grimp)) and checks declared contracts against it. Five built-in contract types — `layers`, `forbidden`, `independence`, `protected`, `acyclic_siblings` — cover the boundary rules this extension generates.

## Why an adapter script

`import-linter`'s CLI emits Rich-formatted text only — no `--format json` flag. The adapter script (`scripts/run-import-linter.py`) calls `import-linter`'s internal `create_report(...)` API, walks the report, and emits `boundary-violations.json` matching the schema at `core/schema/boundary-violations.schema.json`. The reporter ingests that file via `--boundary-format json-violations`.

This is the reference implementation of the pattern documented in `docs/EXTENSIONS.md` § "Backends without machine-readable output".

## Pointers

- agent-redline core: [../../README.md](https://github.com/rore/agent-redline/blob/main/README.md)
- How to build a different extension: [../../docs/EXTENSIONS.md](https://github.com/rore/agent-redline/blob/main/docs/EXTENSIONS.md)
- Policy schema: [../../docs/POLICY_SCHEMA.md](https://github.com/rore/agent-redline/blob/main/docs/POLICY_SCHEMA.md)
- import-linter docs: <https://import-linter.readthedocs.io/>
