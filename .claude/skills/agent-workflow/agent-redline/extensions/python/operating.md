# python — operating-mode notes

Python-specific behavior in addition to the core operating-mode rules.

## Treat as red even if the policy doesn't say so

- **`__init__.py` re-exports in a library.** Adding `from .X import Y` extends the public API. `api-review`.
- **Removing or renaming a public attribute.** Anything imported by name elsewhere is a contract.
- **`async`/`await` on a public function.** Adding/removing changes call sites.
- **`pyproject.toml` `[project] dependencies`** changes — even when not red.
- **Custom `__init_subclass__`, metaclass, or descriptor** changes.

## Dynamic imports MUST NOT bypass contracts

`importlib.import_module()`, `__import__()`, and exec'd `import` are invisible to the static graph. Using them to cross a forbidden layer is structural drift in disguise — the contract still passes.

If a violation is justified, add `ignore_imports` to the offending contract in `pyproject.toml`. That puts the exception in red-zone files, requiring `architecture-review`.

Refuse `importlib.import_module(...)` to satisfy a layered architecture contract.

## TYPE_CHECKING imports

Default profile sets `exclude_type_checking_imports = true`. Cross-layer type hints inside `if TYPE_CHECKING:` are fine. A module imported BOTH at top AND under TYPE_CHECKING — the top one is the real boundary crossing.

## Generated sources

Generated `.py` files (Pydantic from JSON Schema, Strawberry, gRPC stubs, OpenAPI clients) belong in `excludes:`. If found unexcluded, surface and propose the policy update.

## `requirements.txt` vs `pyproject.toml`

`pyproject.toml` `[project.dependencies]` is authoritative. Lock files (`poetry.lock`, `uv.lock`, `requirements.lock`) describe the resolved environment.

When adding a dep: add to `pyproject.toml` AND regenerate the lock. Removing a dep: remove from `pyproject.toml` AND regenerate the lock.

## Django specifics (when the addendum applies)

- **Model change without a corresponding migration in the same PR is a bug.**
- **`RunPython` migrations** are higher-risk than schema-only ones. `architecture-review` in addition to `persistence-review`.
- **`AUTH_USER_MODEL` and the user model class** are architecturally one-way after launch — `security-review`.
- **Settings overrides at deploy.** A `settings.py` change to a default that has a corresponding production env var → `ops-review`.

## FastAPI specifics

- **`Depends(...)` change** on a public router function changes its contract — `api-review`.
- **Pydantic response-model field changes** are API contract changes.

## Async-sync boundaries

Mixing sync DB drivers into async paths or vice versa is a footgun — `architecture-review` for changes that cross. `asyncio.run_in_executor` for offloading sync work to threads is fine; routing a coroutine through it is not.
