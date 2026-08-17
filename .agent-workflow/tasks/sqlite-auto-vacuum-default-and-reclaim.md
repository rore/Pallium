# sqlite-auto-vacuum-default-and-reclaim

Make SQLite space-reclaim systematic: new DBs are born with `auto_vacuum=INCREMENTAL`, and the
background cleaner reclaims free pages (`PRAGMA incremental_vacuum`) after a retention pass that
deleted rows — so the file shrinks instead of only growing. Plus a one-time operational reclaim of
the live DB (currently 430 MB with ~118 MB / 27% free pages after retention). User-approved design:
INCREMENTAL (not FULL) so the hot write path isn't taxed.

<!-- agent-workflow:start -->
**Outcome:**
Every newly-created Pallium SQLite DB uses `auto_vacuum=INCREMENTAL`; after each retention pass that
deletes rows, the cleaner reclaims freed pages so the file size tracks live data instead of only
growing. The live DB is reclaimed once (430 MB → ~312 MB) and converted to INCREMENTAL. No change to
the red `core/service.py`; no change to query/ingest correctness.

**Target:**
Pallium storage layer + background cleaner + the live DB. Files: `storage/sqlite.py`,
`storage/base.py`, `app/dependencies.py`, `app/cleaner.py`, tests, `docs/context/decisions.md`.

**Scope:**
- `storage/sqlite.py` connect hook: `PRAGMA auto_vacuum=INCREMENTAL` (set before `journal_mode=WAL`)
  so a fresh DB adopts it before schema creation; add a `reclaim_free_pages()` that runs
  `PRAGMA incremental_vacuum` outside a transaction (autocommit).
- `storage/base.py`: add `reclaim_free_pages()` to the StorageProvider protocol with a no-op default
  (non-SQLite backends unaffected).
- `app/dependencies.py`: expose `storage` on `BuildResult` so the cleaner can reach it without a
  `core/service.py` passthrough.
- `app/cleaner.py`: after a retention pass that deleted rows, call `built.storage.reclaim_free_pages()`.
- Tests + a `docs/context/decisions.md` entry.
- Operational (one-time, not code): reclaim + convert the live DB.

**Constraints:**
- Do NOT touch `core/service.py` (red zone) — reach storage via `BuildResult.storage`.
- INCREMENTAL, not FULL (user-approved): no per-commit overhead on the write path.
- Setting `auto_vacuum` must not error or add cost on EXISTING DBs (silently ignored without a VACUUM).
- `incremental_vacuum` must run outside a transaction; must not corrupt or block beyond a brief lock.
- Reclaim only when a pass actually deleted rows (skip no-op cycles).
- No query/ingest behaviour change; no internal/product names.

**Completion criteria:**
A fresh DB created through the storage init reports `PRAGMA auto_vacuum == 2` (INCREMENTAL); a DB with
free pages shrinks after `reclaim_free_pages()`; the cleaner calls reclaim after a deleting pass;
existing-DB connections are unaffected (no error); tests cover these; the live DB is reclaimed and
reports `auto_vacuum == 2` with a smaller file and a passing integrity_check.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Redline: the storage files are `watch` (no red touched — `core/service.py` is deliberately
avoided via `BuildResult.storage`), but a storage DEFAULT change affecting all deployments + a live
production reclaim (service downtime, whole-file rewrite) is conservatively Elevated. Multi-file
change (storage + deps + cleaner + tests + docs) → Moderate. Expanded shape; clean-context plan
review required.

**Discovery:**
`storage/sqlite.py:97` `_set_sqlite_pragma` connect hook fires on every connection incl. the first,
before `Base.metadata.create_all` (`storage/sqlite_schema.py:835`) — so `auto_vacuum` set there sticks
on a fresh DB. `app/cleaner.py:57` runs `service.run_retention_pass` and gets `stats` (line 95); the
reclaim goes right after, gated on deletions. `BuildResult` (`app/dependencies.py:37`) exposes only
`service`; `storage` is built at `:318` but not surfaced — add it to the result. Live DB
(`C:/Users/I347041/.pallium/data/pallium.db`): 430 MB, freelist 30202 pages ≈ 118 MB (27%),
`auto_vacuum=0`, WAL. A clean-context review is in flight on pragma ordering (auto_vacuum vs WAL) and
running `incremental_vacuum` outside a transaction.

**Material assumptions:**
- ASSUMPTION: `PRAGMA auto_vacuum=INCREMENTAL` in the connect hook, before WAL, makes NEW DBs adopt it
  (verified by the first connection preceding schema creation). DISPROVED BY: a fresh test DB reports
  `auto_vacuum != 2`. ACTION: set it explicitly during schema-init before `create_all`, or issue a
  one-time `VACUUM` on first init.
- ASSUMPTION: on an existing DB the pragma is a harmless no-op per connection. DISPROVED BY: an error
  or measurable per-connect cost. ACTION: guard to only set when the DB is new/empty.
- ASSUMPTION: `incremental_vacuum` can run via an autocommit connection outside the ORM transaction.
  DISPROVED BY: "cannot VACUUM from within a transaction" or a lock error. ACTION: use a dedicated
  autocommit connection / `engine.connect()` with no active txn; confirmed against the review.

**Plan:**
1. Await the clean-context review; fix ordering/txn details it flags.
2. `storage/sqlite.py`: add `PRAGMA auto_vacuum=INCREMENTAL` first in the connect hook; add
   `reclaim_free_pages()` (autocommit `PRAGMA incremental_vacuum`), returning pages/bytes reclaimed.
3. `storage/base.py`: protocol method with no-op default.
4. `app/dependencies.py`: add `storage` to `BuildResult` + its construction.
5. `app/cleaner.py`: after a deleting pass, call `built.storage.reclaim_free_pages()`; log reclaimed.
6. Tests: fresh-DB `auto_vacuum==2`; reclaim shrinks a DB seeded with deletions; existing-DB no-op.
7. `docs/context/decisions.md`: record the default + rationale (INCREMENTAL + cleaner reclaim).
8. PR → CI green → merge.
9. Operational: stop `Pallium` task (+ kill tree per restart-service.ps1 logic) → on the live DB
   `PRAGMA auto_vacuum=INCREMENTAL; VACUUM; PRAGMA integrity_check;` → verify size + mode → restart →
   confirm `/status` on 19836.

**Verification plan:**
- New-DB default → unit test creates a DB via the storage init and asserts `PRAGMA auto_vacuum == 2`.
- Reclaim shrinks → unit test inserts+deletes to create free pages, calls `reclaim_free_pages()`, asserts page_count/file drops.
- Existing-DB safety → test that connecting to a pre-existing non-auto-vacuum DB does not error and does not force-convert.
- Cleaner wiring → test that a deleting retention pass triggers reclaim (spy/stub), a no-op pass does not.
- No red touch / zones → clean-context redline verdict recorded under Plan review.
- Live reclaim → file size before/after, `auto_vacuum==2`, `integrity_check=ok`, `/status` healthy post-restart.
- CI: agent-workflow, redline, test lanes.

**Plan review:**
<!-- clean-context review in flight (agent); verdict recorded under ## Plan review before implement -->

**Approvals:** Not required at this risk level (Elevated needs clean-context plan review, not human approval). User approved the design direction (INCREMENTAL + stop/vacuum/restart) in-conversation.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

_(pending clean-context review)_
