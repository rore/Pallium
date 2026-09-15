#!/usr/bin/env bash
# agent-workflow UserPromptSubmit hook — "seed".
# Injects the Work-Record rule as factual project context so it is present while
# the model plans. Reliable transport; supported structured mutations use the shared runtime guard.
# FAIL OPEN: on any error, emit nothing (exit 0) — never disrupt a prompt.
set +e
# CTX is interpolated bare into the printf JSON below, so it MUST NOT contain
# a double-quote (") or backslash (\) — either would produce invalid JSON and
# break the hook. Keep the wording to plain punctuation. The hook is
# intentionally dependency-free (no python3/jq), so we do not JSON-encode at
# runtime; this constraint is the trade-off for that.
CTX="Project rule: standalone read-only review, explanation, diagnosis, comparison, or inspection is outside Agent Workflow if the request as a whole asks for neither an implementation plan nor repository mutation; do not create or update a Work Record. If it later expands to either, invoke agent-workflow before that work. Explicit Agent Workflow requests and actions that resume, advance, or pause an existing workflow task remain in scope. For in-scope work, evaluate configured applicability first. Only an explicit whole-change exemption may skip the Work Record. Any non-exempt implementation plan must start by invoking /agent-workflow to create the Work Record and classify risk before code edits."
# Static JSON; printf keeps it dependency-free and stdout-clean.
printf '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":%s}}\n' "\"$CTX\"" 2>/dev/null
exit 0
