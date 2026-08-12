<!-- agent-workflow:start -->
**Outcome:**
<!-- what should be true when complete -->

**Target:**
<!-- affected system, service, or repository -->

**Scope:**
<!-- what may change -->

**Constraints:**
<!-- what must not change or must remain true; "—" if none -->

**Completion criteria:**
<!-- observable outcomes that demonstrate success -->

**Risk:**
<!-- Routine | Elevated | High. Required for expanded shape: anything except (Routine, Simple). -->

**Complexity:**
<!-- Simple | Moderate | Large. Required for expanded shape: anything except (Routine, Simple). -->

**Reason:**
<!-- One- or two-line justification of the (Risk, Complexity) decision. Required on the expanded shape. -->

**Discovery:**
<!-- material findings; references to inspected evidence -->

**Material assumptions:**
<!-- for each: the assumption, the evidence that would disprove it, the action that follows if disproved -->

**Plan:**
<!-- approach, sequence, deviations from convention, stop conditions -->

**Verification plan:**
<!-- each completion criterion and significant risk → verification method -->

**Plan review:**
<!-- routine: self / elevated: clean-context agent review / high: human approver. Record the reference or note "self" for routine within expanded shape. -->

**Approvals:**
<!-- Required at High risk. Recorded verbatim as `Approved by user <timestamp>: "<verbatim quote>"` per the local-mode human-approval decision. See `templates/checkpoints/plan-and-review.md` § "High-risk Approvals format". "—" or "Not required at this risk level" otherwise. -->

**Exceptions:**
<!-- Optional. Records task-level rule waivers per SPEC §11. Empty / "—" when no exception is recorded. When present, see `templates/checkpoints/plan-and-review.md` § Exceptions for the entry shape and non-waivable rules. -->

**State:** Ready to implement
<!-- Ready to implement | Blocked | Ready for review -->
<!-- agent-workflow:end -->

<!--
Implementation reference, Evidence reference, and Result review reference
live in the prose around this marker block (typically under `## Implementation`,
`## Evidence`, `## Result review` headings). The harness exposes them per
SPEC.md §13.1; the marker block carries the planning + classification +
decisional fields.
-->
