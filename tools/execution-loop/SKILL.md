---
name: execution-loop
description: Use when tasks need 3+ steps, involve architecture/refactor seams, behavior-parity risk, or bug/test/CI failures. Skip for trivial one-liners, pure Q&A, or when the user explicitly asks to skip planning.
---

# Execution Loop

## Intent

Use a consistent execution loop that balances speed with correctness:

- plan first for non-trivial work
- re-plan when assumptions break
- prove behavior before marking done
- keep scope minimal and deterministic

## Workflow

1. **Load minimal context**: read only the task-relevant code, docs, and configuration. Avoid broad context loading unless the task proves it necessary.
2. **Plan**: write a short, checkable execution plan in chat or the planning tool when available. Include verification steps, not only implementation steps.
3. **Execute**: implement the minimal-impact root-cause fix. Preserve existing contracts unless the task explicitly calls for changing them.
4. **Re-plan on breakage**: if an assumption fails, stop and re-plan before continuing.
5. **Verify before done**: run the smallest meaningful test slice first, then broader gates as needed. Prefer direct evidence over reasoning from inspection alone.
6. **Close loop**: summarize what changed, what was verified, and any residual risk or follow-up.

## Quality Bar

Before marking work complete, ask:

- Is this the simplest defensible solution?
- Did I verify behavior instead of assuming it?
- Is there a cleaner design than the current approach?
- Did I minimize blast radius and preserve existing contracts?

## Constraints

- do not assume autonomous subagents
- avoid over-engineering simple fixes
- prefer focused diffs and explicit evidence
- do not mix task execution workflow with product-specific roadmap or feature-management rules unless the user explicitly asks for that coupling
