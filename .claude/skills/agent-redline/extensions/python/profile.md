# python — profile

Default zones, boundary rules, and ecosystem options. Bootstrap derives placeholders (`<pkg>`, `<project>`, `<app>`) from the repo. When zones overlap, red wins.

This profile enumerates **three shapes**: layered service (with a Django addendum), library/package, and zone-only fallback. Bootstrap inspects, picks one (or proposes two when ambiguous), developer confirms.

Globs use `**/<pkg>/**` form so they match both src-layout (`src/<pkg>/...`) and flat (`<pkg>/...`) without duplication.

## Shape detection (Phase 1)

| Signal | Implies shape |
|---|---|
| `manage.py` at root **and** `django` in deps | layered service + Django addendum |
| Web framework dep (`fastapi`, `flask`, `starlette`, `aiohttp`, `sanic`, `litestar`, `falcon`, `bottle`) | layered service |
| Layer dirs: `api/`, `domain/`, `application/`, `adapters/`, `infrastructure/`, `core/`, `services/`, `usecases/`, `ports/` | layered service |
| `pyproject.toml` `[project]`, no web dep, package with `__init__.py` re-exports | library / package |
| `apache-airflow`, `prefect`, `dagster`, `luigi` deps; or `dags/`, `pipelines/`, `notebooks/` | zone-only fallback |
| None match | zone-only fallback (developer can adjust) |

**Layout variants** (same shape — bootstrap derives, not separate shapes):
- src-layout: `src/<pkg>/{...}/`. `src/` contains exactly one package.
- flat: `<pkg>/{...}/` at repo root.
- multi-package: each layer is its OWN top-level package at the repo root (`api/`, `core/`, `storage/`, ...). Detected when ≥ 2 top-level dirs each contain `__init__.py` AND none matches the project name from `pyproject.toml`. Contracts use `root_packages` (plural) and top-level layer names.

## Shape: layered service

### Default zones

```yaml
zones:
  red:
    # Persistence migrations (Alembic, framework, yoyo)
    - path: "**/alembic/versions/**.py"
      reason: persistence contract
      checkpoint: persistence-review
    - path: "**/migrations/**.py"
      reason: persistence contract
      checkpoint: persistence-review

    # Outbound port / gateway / repository contracts
    - path: "**/<pkg>/**/ports/**"
      reason: architectural boundary contracts (port interfaces)
      checkpoint: architecture-review
    - path: "**/<pkg>/**/domain/repositories/**"
      reason: domain repository interfaces
      checkpoint: architecture-review

    # Security / auth
    - path: "**/<pkg>/**/security/**"
      reason: auth/security-sensitive code
      checkpoint: security-review
    - path: "**/<pkg>/**/auth/**"
      reason: auth/security-sensitive code
      checkpoint: security-review

    # Self-protection
    - path: ".importlinter"
      reason: dependency-rule definitions
      checkpoint: architecture-review
    - path: "pyproject.toml"
      reason: build / dependency-rule configuration
      checkpoint: architecture-review
    - path: "agent-policy.yaml"
      reason: governance source of truth
      checkpoint: architecture-review

  watch:
    # API entry points — visible, but api-review fires from api: config.
    - path: "**/<pkg>/**/api/**"
      reason: API entry points
    - path: "**/<pkg>/**/routers/**"
      reason: API entry points
    - path: "**/<pkg>/**/views/**"
      reason: API entry points
    - path: "**/<pkg>/**/controllers/**"
      reason: API entry points
    # Domain / adapters / infrastructure / application
    - path: "**/<pkg>/**/domain/**"
      reason: domain code
    - path: "**/<pkg>/**/adapters/**"
      reason: adapter implementations
    - path: "**/<pkg>/**/infrastructure/**"
      reason: infrastructure adapters
    - path: "**/<pkg>/**/application/**"
      reason: application orchestration
    - path: "**/<pkg>/**/services/**"
      reason: application services
    - path: "**/<pkg>/**/usecases/**"
      reason: application use cases
    # Deps / locks
    - path: "requirements*.txt"
      reason: pinned dependencies
    - path: "Pipfile*"
      reason: pipenv dependencies
    - path: "poetry.lock"
      reason: poetry resolved dependencies
    - path: "uv.lock"
      reason: uv resolved dependencies

  blue:
    - path: "**/tests/**"
      reason: tests
    - path: "**/test_*.py"
      reason: tests
    - path: "**/*_test.py"
      reason: tests
    - path: "**/conftest.py"
      reason: pytest configuration
    - path: "docs/**"
      reason: documentation
    - path: "scripts/**"
      reason: local tooling
```

**Deliberately NOT red** (on watch instead): API entry files (path-touch is a poor proxy — use `api:` openapi diff); non-`repositories/`/`ports/` domain modules; adapter/infrastructure implementations (boundary contracts cover the structural part); non-Django `models.py`. Promote in Phase 3 if the repo treats one as structural; widen on evidence, not intuition.

### Default boundary contracts

Bootstrap writes two artifacts in two different vocabularies:

1. **`[tool.importlinter]` in `pyproject.toml`** — the enforcer. Import-linter's syntax: `source_modules`/`forbidden_modules`/`ignore_imports`/`layers`. Pick the subset matching the actual layers.
2. **`boundaries:` in `agent-policy.yaml`** — metadata the reporter surfaces. Schema syntax: `{id, description, from, forbidImports[]}` (see `core/schema/agent-policy.schema.json`). Mirrors (1) so the reporter can describe what's enforced.

Below is the import-linter side; `boundaries:` is the translation.

```toml
[tool.importlinter]
root_package = "<pkg>"
exclude_type_checking_imports = true
# Required when any contract has forbidden_modules pointing at external
# packages (e.g. fastapi, sqlalchemy below). Without it, import-linter
# refuses to run.
include_external_packages = true

# 1. Layered architecture: HIGH -> LOW. Higher (listed first) imports lower;
# lower may not import higher. Domain at the bottom; api/application above.
[[tool.importlinter.contracts]]
name = "Layered architecture"
type = "layers"
layers = [
    "<pkg>.api",
    "<pkg>.application",
    "<pkg>.domain",
]
exhaustive = false

# 2. Hexagonal sidearm: domain MUST NOT import infrastructure/adapters.
# `layers` is linear; this enforces the side direction.
[[tool.importlinter.contracts]]
name = "Domain stays free of infrastructure"
type = "forbidden"
source_modules = ["<pkg>.domain"]
forbidden_modules = ["<pkg>.infrastructure", "<pkg>.adapters"]

# 3. Domain doesn't import any web/runtime framework.
[[tool.importlinter.contracts]]
name = "Domain stays framework-free"
type = "forbidden"
source_modules = ["<pkg>.domain"]
forbidden_modules = [
    "fastapi", "flask", "django", "starlette", "aiohttp",
    "sqlalchemy", "alembic",
]

# 4. Adapters are independent of each other.
[[tool.importlinter.contracts]]
name = "Adapter independence"
type = "independence"
modules = [
    "<pkg>.adapters.email",
    "<pkg>.adapters.payments",
    "<pkg>.adapters.notifications",
]

# 5. Hygiene: top-level package siblings don't form import cycles.
# `ancestors` (plural, required SetField in import-linter 2.x) lists the
# packages whose direct subpackages get the cycle check.
[[tool.importlinter.contracts]]
name = "Acyclic siblings"
type = "acyclic_siblings"
ancestors = ["<pkg>"]
```

**For multi-package layouts**, replace the block above with `root_packages` (plural) and top-level layer names — each layer is its own root package, no parent. Use `forbidden` between layer pairs instead of a single linear `layers` list when the layer graph isn't strictly linear (e.g., several lower layers all callable from the API layer).

```toml
[tool.importlinter]
root_packages = ["api", "application", "core", "providers", "storage"]
exclude_type_checking_imports = true
include_external_packages = true

# Lower layers must not import higher layers. One forbidden contract per
# illegal direction; bootstrap generates these from the actual layer set.
#
# Set `allow_indirect_imports = true`. import-linter's `forbidden` checks
# TRANSITIVE imports by default; in multi-package layouts where one layer
# (e.g. core) bridges many siblings, every other forbidden contract becomes
# unsatisfiable transitively (api -> core -> storage breaks "api ↛ storage").
# These contracts express DIRECT boundaries — set the flag.
[[tool.importlinter.contracts]]
name = "core stays independent of higher layers"
type = "forbidden"
source_modules = ["core"]
forbidden_modules = ["api", "application", "providers", "storage"]
allow_indirect_imports = true

[[tool.importlinter.contracts]]
name = "storage stays independent of higher layers"
type = "forbidden"
source_modules = ["storage"]
forbidden_modules = ["api", "application", "providers"]
allow_indirect_imports = true
# (and so on for each lower layer)
```

Bootstrap adapts:
- Skip absent layers; substitute actual adapter package names.
- Adjust `forbidden_modules` to what the repo actually imports.
- Replace `<pkg>.infrastructure` / `<pkg>.adapters` with the repo's actual paths.
- For multi-package: derive the layer order from the repo's architecture docs (`docs/context/`, `docs/ARCHITECTURE.md`, `AGENTS.md`) when present; ask the developer when not. Generate one `forbidden` contract per illegal direction.

### API contract handling

```yaml
# Committed OpenAPI spec (most common):
api:
  type: openapi-spec-file
  specPath: "openapi/openapi.json"
  diffMode: structural
  checkpoint: api-review

# Or no public surface:
api:
  type: none
```

Generation-from-code (FastAPI `app.openapi()`, Flask-RESTX, drf-spectacular) is roadmap. v1 falls back to path-touch on API entry directories (watch list).

### Default PR-size thresholds

```yaml
prRules:
  maxChangedFiles: { warn: 50, fail: 100 }
  maxLinesChanged: { warn: 1000, fail: 2000 }
```

### Django addendum

If `manage.py` exists at root **and** `django` is in deps, augment (don't replace) the layered-service zones:

```yaml
# Additional red:
zones:
  red:
    - path: "**/settings.py"
      reason: Django settings (auth, middleware, secrets)
      checkpoint: security-review
    - path: "**/settings/*.py"
      reason: Django settings module
      checkpoint: security-review
    - path: "**/urls.py"
      reason: Django URL routing (HTTP surface)
      checkpoint: api-review
    - path: "**/<app>/models.py"
      reason: Django model definitions (paired with migrations)
      checkpoint: persistence-review

# Additional watch:
  watch:
    - path: "**/admin.py"
      reason: Django admin registrations (data exposure surface)
    - path: "**/management/commands/**.py"
      reason: Django management commands (operational scripts)
    # DRF only when djangorestframework is in deps:
    - path: "**/serializers.py"
      reason: DRF serializer contracts
    - path: "**/viewsets.py"
      reason: DRF viewsets
```

```toml
# Additional contracts: cross-app independence + views don't import other apps' models.
[[tool.importlinter.contracts]]
name = "Cross-app independence"
type = "independence"
modules = [
    "<project>.apps.orders",
    "<project>.apps.billing",
    "<project>.apps.notifications",
]

[[tool.importlinter.contracts]]
name = "App views don't reach into other apps' models"
type = "forbidden"
source_modules = ["<project>.apps.*.views", "<project>.apps.*.viewsets"]
forbidden_modules = ["<project>.apps.*.models"]
```

Bootstrap notes:
- Apps live at `apps/` or top-level (`<project>/<app>/`). Inspect to determine.
- `INSTALLED_APPS` in `settings.py` is authoritative; directory layout is a heuristic. Surface any disagreement.
- DRF entries only if `djangorestframework` is in deps.

Django gotchas:
- **`models.py` red zone fires often.** Calibration warning at bootstrap; consider demoting to watch until tuner has run.
- **Migrations are auto-generated.** `RunPython` migrations contain arbitrary code — higher-risk than schema-only.
- **`AUTH_USER_MODEL`** is architecturally one-way after launch — security-review.
- **drf-spectacular integration is roadmap.** v1 uses `urls.py` path-touch.

## Shape: library / package

### Detection

`pyproject.toml` `[project]` / `[tool.poetry]` / `[tool.setuptools]`; no web dep; top-level package with `__init__.py` re-exports.

### Default zones

```yaml
zones:
  red:
    - path: "**/<pkg>/__init__.py"
      reason: public API re-exports
      checkpoint: api-review
    - path: "**/<pkg>/**/*.pyi"
      reason: published type stubs
      checkpoint: api-review
    - path: "**/<pkg>/py.typed"
      reason: PEP 561 type-information marker
      checkpoint: api-review
    - path: "pyproject.toml"
      reason: build / dependency-rule configuration
      checkpoint: architecture-review
    - path: ".importlinter"
      reason: dependency-rule definitions
      checkpoint: architecture-review
    - path: "agent-policy.yaml"
      reason: governance source of truth
      checkpoint: architecture-review

  watch:
    - path: "**/<pkg>/**/[!_]*.py"
      reason: public (non-underscored) library modules
    - path: "CHANGELOG.md"
      reason: published changelog
    - path: "README.md"
      reason: README is part of the published package

  blue:
    - path: "tests/**"
      reason: tests
    - path: "**/test_*.py"
      reason: tests
    - path: "docs/**"
      reason: documentation
```

### Default boundary contracts

```toml
[tool.importlinter]
root_package = "<pkg>"

# 1. Private (leading-underscore) modules only imported within their own subtree.
[[tool.importlinter.contracts]]
name = "Private modules stay internal"
type = "protected"
protected_modules = ["<pkg>._internals", "<pkg>._compat", "<pkg>._utils"]
allowed_importers = ["<pkg>"]

# 2. Acyclic siblings.
[[tool.importlinter.contracts]]
name = "Acyclic siblings"
type = "acyclic_siblings"
ancestors = ["<pkg>"]
```

Only generate the `protected` contract when the repo actually has leading-underscore modules; don't fabricate.

### Default PR-size thresholds

```yaml
prRules:
  maxChangedFiles: { warn: 20, fail: 50 }
  maxLinesChanged: { warn: 500, fail: 1000 }
```

## Shape: zone-only fallback

For pipelines, notebook-heavy ML repos, mixed monorepos, scripts-and-glue.

```yaml
zones:
  red:
    - path: "**/migrations/**.py"
      reason: persistence contract
      checkpoint: persistence-review
    - path: "**/alembic/versions/**.py"
      reason: persistence contract
      checkpoint: persistence-review
    - path: "dags/**"
      reason: pipeline definitions
      checkpoint: pipeline-review
    - path: "pipelines/**"
      reason: pipeline definitions
      checkpoint: pipeline-review
    - path: "agent-policy.yaml"
      reason: governance source of truth
      checkpoint: architecture-review
  watch:
    - path: "**/*.py"
      reason: pipeline / glue code
    - path: "notebooks/**"
      reason: notebook artifacts
    - path: "requirements*.txt"
      reason: pinned dependencies
  blue:
    - path: "tests/**"
      reason: tests
    - path: "docs/**"
      reason: documentation

boundaryAdapter:
  outputFormat: none

prRules:
  maxChangedFiles: { warn: 30, fail: 80 }
  maxLinesChanged: { warn: 800, fail: 1500 }
```

Reporter skips boundary parsing. Zones, persistence/security signals, PR-size still run.

## Ecosystem options

Ask in Phase 3 and include if relevant.

**Multi-database services:**
```yaml
persistence:
  migrationPaths:
    - "**/alembic/versions/**.py"
    - "**/<pkg>/persistence/migrations/**.py"
    - "**/db/migrations/**.py"
  checkpoint: persistence-review
```

**Third-party SDK contracts:**
```yaml
zones:
  red:
    - path: "**/<pkg>/adapters/<vendor>/dto/**"
      reason: third-party API contract surface
      checkpoint: api-review
```

**Tasks / queues as a public-ish surface** (Celery, RQ, FastAPI background):
```yaml
zones:
  watch:
    - path: "**/<pkg>/tasks/**"
      reason: task signatures are a contract for callers
    - path: "**/<pkg>/jobs/**"
      reason: job signatures are a contract for callers
```

## Build / test commands

| Action | Command |
|---|---|
| Run all tests | `pytest` |
| Run boundary check | `python scripts/run-import-linter.py --out build/import-linter-report.json` |
| Run local agent-redline check | `bash scripts/agent-redline-check.sh` |

## Gotchas

- **Dynamic imports bypass contracts.** `importlib.import_module()` and `__import__()` are invisible to the static graph. Operating-mode forbids them as a workaround.
- **`if TYPE_CHECKING:` imports.** `exclude_type_checking_imports = true` (top-level) suppresses these. Default profile sets it.
- **Namespace packages (PEP 420).** Set `root_package` to the portion (`mynamespace.foo`), not the namespace.
- **src-layout requires the package to be importable.** CI installs editable (`pip install -e .`); flat-layout has the cwd on `sys.path`.
- **Layer dirs need `__init__.py`** (even empty), or `layers` doesn't see them. Bootstrap warns if missing.
- **`pyproject.toml` is authoritative** for package's own deps; `requirements.txt` (and lock files) describe the resolved environment.
- **Django `INSTALLED_APPS` is authoritative** over directory layout. Bootstrap surfaces any disagreement.

## Pointers

- import-linter docs: <https://import-linter.readthedocs.io/>
- contract types: <https://import-linter.readthedocs.io/en/stable/contract_types/index.html>
