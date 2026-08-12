# verify

The Verification field names every completion criterion from Establish Context and points each at the check that verifies it. Write this *before* you code — the act of writing it tells you whether your completion criteria are checkable.

Structured-claim semantics: SPEC §13.3.

## What goes in the field

One or two lines naming the checks. Name the test class or job, not "the test suite":

> WalletRetryTest plus the required wallet-service CI job.

If the completion criterion is concrete and you have a CI surface, the field is short. Replace any "the developer can manually check that..." with an automated check when the work is mechanically checkable.

## Verification plan grammar (expanded shape)

The expanded shape's Verification plan is per-criterion. Each line pairs a criterion with the method:

- `<criterion> → <method>` — Unicode right-arrow (preferred)
- `<criterion> -> <method>` — ASCII fallback
- `<criterion> — <method>` — em-dash separator
- `<method>: <criterion>` — method-first, colon-separated
- `manual: <description>` — explicit manual verification

The `evidence.criteria_have_methods` predicate is advisory: counts unmapped lines, shows examples. **Adequacy stays a reviewer judgment** (SPEC §9.7).

## Evidence prose (outside the marker block)

The marker block names *what* verifies the work. The actual result — CI run link, test report, commit it was tested against — lives in surrounding prose under an `## Evidence` heading. The checker validates the Verification field exists and is non-empty; later harness work will validate that the recorded reference resolves and the revision matches PR head.

**The PR is the evidence surface** (SPEC §13.1). The Work Record names what verifies the work; the PR carries the result. Do not duplicate the PR's CI runs, comments, or status checks in the Work Record.

## State transition

Verify unblocks `Ready to implement` → `Ready for review`:

- You ran the verification you recorded.
- It passed (or any failure is named in the Work Record with an action item).
- The revision the verification ran against is recorded.

Then update State.

## Failed verification

A failed required check is not a passing result. Do not advance State to `Ready for review` with a failing CI job and a "will investigate" note. Either:

- Fix the cause and re-run.
- Update State to `Blocked` and name the failure + next step in surrounding prose.

The `evidence.failure_not_claimed_as_success` predicate (advisory) scans for tightly-localised contradictions — a failure marker and success marker within 300 chars of each other referencing the same CamelCase test identifier. If you wrote `❌ FAILED` then `✅ passed` for the same test in the same span, it surfaces.

## What this checkpoint is not

- Not where you invent new acceptance criteria mid-task. New criteria → re-planning.
- Not where you record everything you tried. Record what proves the change.
- "Bug fixes should include a regression test that fails before the fix when practical" — SPEC §9.6, a SHOULD not a MUST. Note an exception if you have one.
