#!/usr/bin/env bash
# agent-workflow PostToolUse(ExitPlanMode) hook — "reinforce".
# After a plan is approved, re-assert the first step so implementation begins by
# creating the Work Record. Model-directed (not a guarantee). FAIL OPEN.
set +e
CTX="The plan is approved. Per the repository workflow, before editing any file under src/, invoke the /agent-workflow skill now to create the Work Record, as the approved plan specifies."
printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":%s}}\n' "\"$CTX\"" 2>/dev/null
exit 0
