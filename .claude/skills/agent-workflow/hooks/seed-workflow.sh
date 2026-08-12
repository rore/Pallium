#!/usr/bin/env bash
# agent-workflow UserPromptSubmit hook — "seed".
# Injects the Work-Record rule as factual project context so it is present while
# the model plans. Reliable transport, not enforcement (the gate enforces).
# FAIL OPEN: on any error, emit nothing (exit 0) — never disrupt a prompt.
set +e
CTX="Project rule: changes that modify code under a guarded path require a Work Record, created via the agent-workflow skill. Any implementation plan for such a change must include, as its first implementation step, invoking the /agent-workflow skill (which writes the Work Record and classifies risk) before any code edit."
# Static JSON; printf keeps it dependency-free and stdout-clean.
printf '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":%s}}\n' "\"$CTX\"" 2>/dev/null
exit 0
