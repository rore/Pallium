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
CTX="Project rule: every engineering task is recorded in a Work Record, created via the agent-workflow skill. This applies to any change that is part of a task — NOT only changes under guarded paths. (Guarded paths are simply the subset the plan-mode gate enforces automatically; a change outside them still needs a Work Record if it is a task.) Any implementation plan must include, as its FIRST implementation step, invoking the /agent-workflow skill (which writes the Work Record and classifies risk) before any code edit."
# Static JSON; printf keeps it dependency-free and stdout-clean.
printf '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":%s}}\n' "\"$CTX\"" 2>/dev/null
exit 0
