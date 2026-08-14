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
No change to what the lookup/expansion tools DO — exposure/guidance/description only. Preserve the Codex `test_codex_integration.py` invariants (`"MANDATORY" not in` the block — applies to BOTH the neutral and the strong variant; `pallium_query`/`pallium_expand` remain present/optional). Keep the marker-bounded block install idempotent for same-arm re-installs, but REPLACE the block when the arm changes (Claude must mirror Codex's replace). `--guidance-strength` defaults to the neutral arm so a plain install is unchanged in strength (only the blanket anti-pull discouragement is removed; the anti-dup clause is retained). No internal/external product names in committed artifacts. Match surrounding style.

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
- A2 (REVISED — REFUTED by review): `test_mcp_server.py:128` asserts an EXACT set of 7 tools while `server.py` registers 15; it "passes" only because the module is `importorskip("mcp")`-skipped when `mcp[cli]` is absent (this env + CI → "15 skipped"). So the reconcile is MANDATORY, not conditional. Reconcile to a subset/superset check against the actual registered set (exact-set is brittle). The full registered set is 15; 8 are absent from guidance (`pallium_search_history`, `pallium_expand_source`, `pallium_remember`, `pallium_correct`, `pallium_supersede`, `pallium_forget`, `pallium_forget_source`, `pallium_record_outcome`) — but only the 2 P1 tools are in THIS feature's scope; the rest are noted, not added.
- A3: Removing `--stdio` from the plugin `.mcp.json` is safe — CONFIRMED (`server.py:main` reads transport from env only; no argv; `test_codex_integration.py:33` uses `--stdio` only as rewrite INPUT, asserts module args out, never asserts `--stdio` survives).

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

**State:** Ready to implement
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
3. **Guidance-strength lever (block-variant).** Add `--guidance-strength {tool-only,strong}` (default `tool-only`) to both `setup_claude_code.main` and `setup_codex.main`. The lever is the **installed block variant**, NOT install-or-not-a-skill (a skill is agent-invoked → whether the agent reaches for it is itself the dependent variable Experiment-1 measures; always-present block text is a clean arm boundary). `tool-only` installs the neutral-permit block (permit line + tool descriptions). `strong` installs `base + an appended directive paragraph` (e.g. "When you resume or continue prior work on this task, call `pallium_search_history` first…") authored to AVOID the token "MANDATORY" and the two banned legacy strings so `test_codex_integration.py:269-276` invariants hold. Store the strong variant so the test can cover it (parameterized block builder in `claude_md_block.py`; Codex strong = base AGENTS.md + the same appended directive, generated in `setup_codex`). **Arm attribution is operator-side/manual for Experiment-1** — recorded in the setup output + an arm marker comment inside the installed block + the runbook; it is NOT machine-attributable by the server-side funnel (setup stdout / a CLAUDE.md comment are invisible to `/status`). Do NOT over-claim C2 as funnel-attributable.
3b. **Claude install must REPLACE the marker block.** `setup_claude_code._append_claude_md_block` (:150-151) early-returns if `<!-- pallium:start -->` already exists → flipping arms would silently no-op. Mirror Codex's `_replace_agents_md_block` so a re-install with a different `--guidance-strength` rewrites the marker-bounded block. Add a test asserting the block content changes on re-install with a different strength.
4. **Tool-description polish** (`app/mcp/server.py`): tighten `pallium_search_history` wording to add a task-start/resume trigger phrase; keep `pallium_expand_source` as-is or minor. Description-only, no behavior.
5. **`--stdio` reconcile.** Remove the no-op `"--stdio"` from `integrations/codex/.mcp.json:5` (transport is env-driven). Leave `test_codex_integration.py:33` fixture as legacy-input coverage of the rewrite.
6. **Tests.** Add: Claude block + Codex block contain the permit line and `pallium_search_history`/`pallium_expand_source`; the anti-pull discouragement drops the blanket "Query every turn" clause but RETAINS the anti-dup "re-query for something already in the injected block" clause; setup `--guidance-strength strong` installs the strong variant and `tool-only` the neutral one, default `tool-only`, and Claude re-install with a different strength REPLACES the block (content changes); strong variant satisfies the `test_codex_integration.py:269-276` invariants (`"MANDATORY" not in`, banned strings absent, `pallium_query`/`pallium_expand` present); `.mcp.json` no longer carries `--stdio`. **Reconcile `test_mcp_server.py:121-128`** from the exact 7-tool set to a subset assertion (the registered set is 15; assert the expected names are a subset of / present in the registered set so future tool additions don't re-break it) — note the module is `importorskip`-gated.

## Verification plan

- **C1 (permit + expose):** content tests assert both deployed blocks contain the permit/encourage line and list `pallium_search_history`/`pallium_expand_source`; the anti-pull Do-not bullet no longer discourages deliberate pulls; Codex invariants (`"MANDATORY" not in`, `pallium_query`/`pallium_expand` present) hold.
- **C2 (lever):** `setup … --guidance-strength strong` vs `tool-only` installs the corresponding block variant (assert distinguishing text) and records the arm in output; default is `tool-only`.
- **C3 (skills + descriptions + stdio):** Codex SKILL.md lists the P1 tools + `[+expand]`; a Claude Code skill exists with the P1 tools; `pallium_search_history` description carries a resume/task-start trigger; `.mcp.json` has no `--stdio`.
- **C4 (behavioral smoke):** documented manual/scripted check that under the strong arm an agent is prompted to pull unprompted (no live network assertion in CI).
- **Regression:** `python -m pytest tests/ -q` green (modulo the known-benign config test); `test_codex_integration.py` + `test_mcp_server.py` pass (latter reconciled).

## Plan review

Clean-context technical review (Plan agent, fresh context). **Verdict: APPROVE-WITH-CHANGES**; risk stays Elevated (guarded edits are CLI args + docstring strings only; nothing touches `core/`/`api/` or tool behavior). A1 (setup-CLI lever seam) and A3 (`--stdio` removal) confirmed against code. Findings folded into the plan:
- **[BLOCKER] A2 refuted** → the `test_mcp_server.py:128` reconcile is mandatory; it "passes" only because the module is `importorskip("mcp")`-skipped. Reconcile to a subset check over the actual 15 registered tools.
- **[SHOULD] arm attribution** → operator-side/manual for Experiment-1 (setup output + block marker + runbook); NOT funnel-machine-attributable — C2 reworded to not over-claim.
- **[SHOULD] lever = block-variant** (not install-or-not-a-skill, which would confound the dependent variable); skill kept for discoverability only. Endorsed.
- **[SHOULD] Claude replace-on-reinstall** (step 3b) → mirror Codex `_replace_agents_md_block` so flipping arms isn't a silent no-op; test added.
- **[SHOULD] strong variant location + invariants** → strong = base + appended directive (both integrations), authored to avoid "MANDATORY"/banned strings; test covers it.
- **[NIT] permit-line scoping** → drop the blanket "Query every turn" clause, RETAIN the anti-dup clause; scope the permit line to a task-start/resume trigger. Folded into steps 1 + 6.

## Implementation

Not started. State `Blocked` (in planning) until the clean-context review returns and State flips to `Ready to implement`.
