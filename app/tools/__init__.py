"""app.tools package — operational tooling not on the request-serving path.

Each tool is invocable via ``python -m app.tools.<name>``. Tools are
allowed to reach into `storage/` and `core/` — they run offline, not
inside the FastAPI event loop.
"""
