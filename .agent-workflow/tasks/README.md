# Work Records

Each file here is a Work Record for one task — created by the `/agent-workflow` skill at task start, updated at each checkpoint, and left as the durable audit trail after merge.

**File naming:** `{slug}.md` where `{slug}` is derived from the branch name (prefix like `feat/`, `fix/`, `chore/` stripped; `/` replaced with `-`).

**Shape:**
- `(Routine, Simple)` → compact (marker block only)
- Anything else → expanded (marker block + Implementation / Evidence / Result review prose sections)

See `docs/agent-workflow/` for per-checkpoint reference docs, or invoke `/agent-workflow` to start a task.
