#!/usr/bin/env bash
# agent-workflow UserPromptSubmit hook — "seed".
# Injects the Work-Record rule as factual project context so it is present while
# the model plans. Reliable transport, not enforcement (the gate enforces).
# FAIL OPEN: on any error, emit nothing (exit 0) — never disrupt a prompt.
set +e
# CTX is interpolated bare into the printf JSON below, so it MUST NOT contain
# a double-quote (") or backslash (\) — either would produce invalid JSON and
# break the hook. Keep the wording to plain punctuation. The hook is
# intentionally dependency-free (no python3/jq), so we do not JSON-encode at
# runtime; this constraint is the trade-off for that.
CTX="Project rule: invoke the agent-workflow skill before planning or editing. It first evaluates any configured applicability policy. Only an explicit whole-change exemption may skip the Work Record; otherwise every engineering task is recorded. Any implementation plan for a non-exempt task must include, as its FIRST implementation step, invoking /agent-workflow to create the Work Record and classify risk before any code edit."
# Static JSON; printf keeps it dependency-free and stdout-clean.
printf '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":%s}}\n' "\"$CTX\"" 2>/dev/null
exit 0
