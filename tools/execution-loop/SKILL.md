---
name: execution-loop
description: Use when tasks need 3+ steps, involve architecture/refactor seams, behavior-parity risk, or bug/test/CI failures. Skip for trivial one-liners, pure Q&A, or when the user explicitly asks to skip planning.
---

# Execution Loop

## Intent

Use a consistent execution loop that balances speed with correctness:

- plan first for non-trivial work
- review your own plan before implementing
- ensure regression test coverage exists before changing code
- re-plan when assumptions break
- review your own implementation before marking done
- prove behavior before marking done
- keep scope minimal and deterministic

## Workflow

1. **Load minimal context**: read only the task-relevant code, docs, and configuration. Avoid broad context loading unless the task proves it necessary.
2. **Plan**: write a short, checkable execution plan. Include verification steps, not only implementation steps.
3. **Review your plan**: before implementing, review the plan as if you are the architect. Check: does it fit the architecture boundaries? Is it the smallest valuable change? Does it preserve existing contracts? Are there simpler alternatives? Iterate until there are no material issues.
4. **Ensure regression coverage**: before changing code, check that the behavior you are about to modify has existing test coverage. If it does not, add tests for the current behavior first and commit them separately. This establishes a regression baseline — if your change breaks something, the test suite catches it.
5. **Execute**: implement the minimal-impact change. Preserve existing contracts unless the task explicitly calls for changing them.
6. **Re-plan on breakage**: if an assumption fails, stop and re-plan before continuing.
7. **Review your implementation**: after implementing, review your own diff as if you are a code reviewer. Check for: correctness issues, missed edge cases, unnecessary complexity, contract violations, variable naming clarity, and consistency with surrounding code. Fix issues before proceeding. Use a subagent for the review when the change is large enough to benefit from a fresh perspective.
8. **Verify before done**: run the smallest meaningful test slice first, then broader gates as needed. Prefer direct evidence over reasoning from inspection alone.
9. **Close loop**: summarize what changed, what was verified, and any residual risk or follow-up.

## Quality Bar

Before marking work complete, ask:

- Is this the simplest defensible solution?
- Did I verify behavior instead of assuming it?
- Is there a cleaner design than the current approach?
- Did I minimize blast radius and preserve existing contracts?
- Did I ensure regression tests existed before I changed anything?
- Did I review my own plan and implementation, or did I skip straight to done?

## Constraints

- do not assume autonomous subagents
- avoid over-engineering simple fixes
- prefer focused diffs and explicit evidence
- do not mix task execution workflow with product-specific roadmap or feature-management rules unless the user explicitly asks for that coupling
