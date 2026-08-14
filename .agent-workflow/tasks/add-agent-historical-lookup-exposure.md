# Work Record — add-agent-historical-lookup-exposure

Task branch: `feat/add-agent-historical-lookup-exposure`
Roadmap item: `roadmap/features/add-agent-historical-lookup-exposure.md`

<!-- agent-workflow:start -->
**Outcome:**
On a fresh local install, the deployed memory guidance (Claude Code + Codex) *permits/encourages* a deliberate `pallium_search_history` pull when prior work on the task may exist — instead of discouraging proactive querying — and Experiment 1 has a **guidance-strength lever** it can set and record as an arm label. Both integrations expose `pallium_search_history` / `pallium_expand_source` with clear when-to-use text; the stale Codex skill is refreshed and a Claude Code equivalent exists; tool descriptions read as self-explanatory for unprompted use; the no-op `--stdio` is reconciled.

**Target:**
Pallium repo. Guarded: `app/cli/setup_claude_code.py` + `app/cli/setup_codex.py` (guidance-strength arg + install selection), `app/mcp/server.py` (tool-description wording — description-only, no behavior). Non-guarded: `integrations/claude-code/claude_md_block.py`, `integrations/codex/AGENTS.md`, `integrations/codex/skills/pallium-memory/SKILL.md`, a new Claude Code historical-lookup skill, `integrations/codex/.mcp.json`, `tests/`.

**Scope:**
Delivered as **1 PR**. (1) Guidance edits to both deployed blocks: keep the automatic-injection "~90%" framing, ADD an explicit permit/encourage line for a deliberate historical pull, and refine the "Query every turn" Do-not bullet so it targets injection-duplication (not deliberate historical pulls). (2) Refresh the Codex `pallium-memory` SKILL.md to include `pallium_search_history` / `pallium_expand_source` (+ fix `[+source]`→`[+expand]`); add an equivalent Claude Code skill. (3) Experiment-1 guidance-strength lever: a `--guidance-strength {tool-only,strong}` arg on both setup entrypoints selecting which block variant (neutral-permit vs strong-directive) is installed, recorded in setup output as the arm label. (4) Tool-description wording polish in `app/mcp/server.py`. (5) Reconcile the no-op `--stdio` in the plugin `.mcp.json`. (6) Tests + reconcile the stale `test_mcp_server.py` exact-tool-set assertion.
MAY NOT touch: tool *behavior* (retrieval/scoring/source_only semantics); the funnel persistence/rollup (separate, merged feature); running the actual Experiment-1 measurement window.

**Constraints:**
No change to what the lookup/expansion tools DO — exposure/guidance/description only. Preserve the Codex `test_codex_integration.py` invariants (`"MANDATORY" not in` the block; `pallium_query`/`pallium_expand` remain present/optional). Keep the marker-bounded block install idempotent. `--guidance-strength` defaults to the neutral arm so a plain install is unchanged in strength (only the anti-pull discouragement is removed). No internal/external product names in committed artifacts. Match surrounding style.

**Completion criteria:**
Feature "Done When" 1–4: (1) fresh-install guidance permits/encourages a deliberate pull (no discouragement) and both integrations expose the P1 tools with when-to-use; (2) a guidance-strength lever (`--guidance-strength`) selects tool-only vs strong and records the arm; (3) Codex skill refreshed with P1 tools + Claude Code equivalent exists + tool descriptions self-explanatory + `--stdio` reconciled; (4) a behavioral smoke check shows an agent could pull unprompted under the strong arm (documented; not a live network test). Plus `python -m pytest tests/ -q` green (modulo known-benign `test_config.py::test_prompt_variants_legacy_fallback_unaffected`).

**Risk:** Elevated

**Complexity:** Moderate

**Reason:**
Guarded but no RED: touches `app/cli/` (setup arg + install selection) and `app/mcp/server.py` (tool-description STRINGS only, no behavior change) — plus non-guarded `integrations/` guidance + skills. No persistence, no `core/`/`api/` contract, no retrieval-behavior change. Elevated (guarded, conservative). Moderate: several coordinated files (two blocks + two skills + two setup entrypoints + descriptions + tests), meaningful-but-bounded.

**Discovery:**
Recorded under `## Discovery`. Key: guidance is STATIC install-time text (not service-generated) → lever is a setup-CLI arg, not a config flag; the P1 tools are ALREADY listed passively in both blocks (missing = a permit/encourage line; the "Query every turn" Do-not bullet discourages); Codex SKILL.md is stale (no P1 tools, `[+source]`); no Claude Code skill scaffold exists (greenfield); `test_mcp_server.py:128` asserts a stale exact 7-tool set that excludes the registered P1 + W3 tools (must reconcile); `--stdio` no-op lives only in the plugin `.mcp.json:5` (setup CLI already rewrites it).

**Material assumptions:**
- A1: The lever is best expressed as a setup-CLI `--guidance-strength` arg selecting the installed block variant, because guidance is static install-time text (no per-response generation seam). Disproof: a service block-generation path is found → plug the lever there instead.
- A2: `test_mcp_server.py:128`'s exact-set assertion currently passes (the full funnel suite was green) — so it may already include the P1 tools or be a subset/skip. Verify before editing; if touching descriptions/registration trips it, update to the actual registered set (or a subset check). Disproof: it's already correct → no change.
- A3: Removing `--stdio` from the plugin `.mcp.json` is safe (it's ignored; transport is env-driven). The `test_codex_integration.py:33` fixture uses `--stdio` as *input* asserting the setup rewrites it — leave that fixture as legacy-input coverage. Disproof: something parses `--stdio` → keep it.

**Plan:**
See `## Plan`. Single PR. Guidance edits → skill refresh + new Claude skill → `--guidance-strength` lever in both setup entrypoints → tool-description polish → `--stdio` reconcile → tests (incl. reconcile stale assertion). Stop condition: if the lever turns out to require a service block-generation change (contradicting A1), stop and re-scope.

**Verification plan:**
See `## Verification plan` — each completion criterion → method (block-content tests for the permit line + P1-tool presence; setup `--guidance-strength` arm-selection test; Codex-invariant preservation; `--stdio` reconcile assertion; reconciled tool-set test; full `pytest`).

**Plan review:**
Clean-context agent review REQUIRED (Elevated). Reference recorded in `## Plan review` before State → Ready to implement.

**Approvals:**
Not required at this risk level (Elevated). Standing overnight package mandate covers proceeding.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Discovery

Full seam map (`path:line`):

**Discouraging guidance (DEPLOYED):** `integrations/claude-code/claude_md_block.py` `CLAUDE_MD_BLOCK` → installed into `~/.claude/CLAUDE.md`. Line 9-10 injection "~90% / don't duplicate with manual queries"; line 86 Do-not "Query every turn or re-query…"; lines 26-32 already list `pallium_search_history`/`pallium_expand_source` under "Reach for these when you need them"; lines 96-101 abstention policy (opt-in, default off). `integrations/codex/AGENTS.md` → `~/.codex/AGENTS.md`: line 6-7 same injection framing; line 81 same Do-not; lines 19-27 same passive tool listing. Distinction: the "~90%" text is about INJECTION; the Do-not bullet is about TOOL PULLS.

**Install path (static text, no service generation):** Claude — `app/cli/setup_claude_code.py` `_get_claude_md_block()` (:133-137) execs `claude_md_block.py`; `_append_claude_md_block()` (:140-154) writes marker-bounded block; `install()` (:202-227) also `_register_mcp`/`_register_hooks`; `_verify_service` (:191-197) reads `/status`. Codex — `app/cli/setup_codex.py` `_get_agents_md_block()` (:296-299), `_append/_replace_agents_md_block()` (:302-334), `_ensure_mcp_server()` (:173-190) writes `args=["-m","app.run","mcp"]` (:181). CLI routing `app/run.py:107-113`. → Lever seam = setup CLI arg selecting the installed block/skill (NOT a service flag).

**Codex skill (STALE):** `integrations/codex/skills/pallium-memory/SKILL.md` — documents only `pallium_ingest`/`pallium_query`/`pallium_expand`/`pallium_query_debug` (:21-33); NO P1 tools; uses `[+source]` (:30, should be `[+expand]`); Do-not discourages proactive pulls (:38-39).

**Claude Code skill:** none for historical lookup. `.claude/skills/` has only `agent-workflow` + `minimap-roadmap`. Only P1 guidance = the passive block fragment. New skill is greenfield; mirror the Codex `skills/<name>/SKILL.md` shape.

**Tool descriptions:** `app/mcp/server.py` `pallium_search_history` docstring (:69-78) already reads well ("look back at prior raw work when picking up related work"); `pallium_expand_source` (:187-197) clear/sequenced. Wording polish only (add a "when resuming / at task start" trigger phrase to search_history).

**`--stdio` no-op:** `integrations/codex/.mcp.json:5` `"args": ["--stdio"]`; `app/mcp/server.py:main()` (:467-482) reads transport from env only, no argv/argparse. Setup CLI generates `args=["-m","app.run","mcp"]` instead.

**Config pattern (if a status flag is wanted):** `app/config.py` `ObservabilityConfig` — `shadow_subtask_selector_enabled` (:89), `historical_lookup_funnel` (:91-97); parse idiom `_resolve_bool_value("PALLIUM_OBSERVABILITY_<NAME>", env, _read_nested(...,"observability","<name>"), default)` (:324-341).

**Tests:** `tests/test_codex_integration.py` — block replacement (:168-187), content invariants (:269-276: `"MANDATORY" not in`, `pallium_query`/`pallium_expand` present), MCP args rewrite `--stdio`→module (:15-46). `tests/test_mcp_server.py:121-128` — STALE exact 7-tool set assertion (excludes P1 + W3 tools) → reconcile. No test covers `setup_claude_code.py`/`claude_md_block.py` content (gap to fill).

## Plan

Single PR on `feat/add-agent-historical-lookup-exposure`.

1. **Guidance — permit deliberate pulls (both deployed blocks).** In `integrations/claude-code/claude_md_block.py` and `integrations/codex/AGENTS.md`: keep the automatic-injection "~90%" framing; ADD one explicit line permitting/encouraging a deliberate `pallium_search_history` pull when resuming or building on prior work on the task; refine the "Query every turn" Do-not bullet to clearly target *injection-duplication* (re-querying for what's already injected), NOT deliberate historical pulls. Preserve the `test_codex_integration.py:269` invariants.
2. **Skills.** Refresh `integrations/codex/skills/pallium-memory/SKILL.md` to document `pallium_search_history` + `pallium_expand_source` (when-to-use, result meaning) and fix `[+source]`→`[+expand]`; align the do-not framing to permit deliberate pulls. Add an equivalent Claude Code historical-lookup skill (greenfield) mirroring the Codex skill shape at a location the Claude setup can reference.
3. **Guidance-strength lever.** Add `--guidance-strength {tool-only,strong}` (default `tool-only`) to both `setup_claude_code.main` and `setup_codex.main`. `tool-only` installs the neutral-permit block (relies on tool descriptions + the permit line). `strong` installs a block variant with an explicit at-task-start directive (e.g. "when you resume or continue prior work, call `pallium_search_history` first") and/or the stronger skill. Record the chosen arm in the setup output (and, if cheap, an arm marker inside the installed block) so Experiment 1 can attribute. No service config flag required (per A1); if a `/status`-reported flag is wanted for symmetry it follows the `historical_lookup_funnel` idiom — optional, keep minimal.
4. **Tool-description polish** (`app/mcp/server.py`): tighten `pallium_search_history` wording to add a task-start/resume trigger phrase; keep `pallium_expand_source` as-is or minor. Description-only, no behavior.
5. **`--stdio` reconcile.** Remove the no-op `"--stdio"` from `integrations/codex/.mcp.json:5` (transport is env-driven). Leave `test_codex_integration.py:33` fixture as legacy-input coverage of the rewrite.
6. **Tests.** Add: Claude block + Codex block contain the permit line and `pallium_search_history`; setup `--guidance-strength strong` installs the strong variant and `tool-only` the neutral one (+ arm recorded); Codex invariants preserved; `.mcp.json` no longer carries `--stdio`. Reconcile `test_mcp_server.py:128` to the actual registered tool set (verify first per A2).

## Verification plan

- **C1 (permit + expose):** content tests assert both deployed blocks contain the permit/encourage line and list `pallium_search_history`/`pallium_expand_source`; the anti-pull Do-not bullet no longer discourages deliberate pulls; Codex invariants (`"MANDATORY" not in`, `pallium_query`/`pallium_expand` present) hold.
- **C2 (lever):** `setup … --guidance-strength strong` vs `tool-only` installs the corresponding block variant (assert distinguishing text) and records the arm in output; default is `tool-only`.
- **C3 (skills + descriptions + stdio):** Codex SKILL.md lists the P1 tools + `[+expand]`; a Claude Code skill exists with the P1 tools; `pallium_search_history` description carries a resume/task-start trigger; `.mcp.json` has no `--stdio`.
- **C4 (behavioral smoke):** documented manual/scripted check that under the strong arm an agent is prompted to pull unprompted (no live network assertion in CI).
- **Regression:** `python -m pytest tests/ -q` green (modulo the known-benign config test); `test_codex_integration.py` + `test_mcp_server.py` pass (latter reconciled).

## Plan review

Clean-context agent review requested (Elevated) — reference recorded here on completion. Review focus: (a) is the setup-CLI arg the right lever seam (A1), or is there a service generation path? (b) does removing the anti-pull discouragement risk query-spam / does the permit line stay scoped to deliberate historical pulls? (c) `test_mcp_server.py:128` reconciliation — confirm the actual registered set; (d) is a two-block-variant install the simplest lever, or is install-or-not-a-skill cleaner?

## Implementation

Not started. State `Blocked` (in planning) until the clean-context review returns and State flips to `Ready to implement`.
