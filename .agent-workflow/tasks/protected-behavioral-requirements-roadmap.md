<!-- agent-workflow:start -->
**Outcome:**
The canonical Minimap queues a high-priority protected behavioral-requirements regression suite immediately after urgent Relay wake reliability.

**Target:**
Pallium roadmap only.

**Scope:**
`roadmap/board.md`, `roadmap/features/add-protected-behavioral-requirements-regression-suite.md`, and this Work Record.

**Constraints:**
Do not implement the suite, CI gate, manifest, tests, or runtime changes. Keep the item concise, requirement-focused, and separate from implementation tests.

**Completion criteria:**
The board placement and feature item preserve the requested immutable-by-default behavioral contract, human-approved evolution rule, enforcement expectations, seed Relay requirements, and done criteria.

**Risk:** Routine

**Complexity:** Simple

**Reason:**
Clean-context redline classification is BLUE: roadmap and Work Record paths only, with no boundary or checkpoint findings.

**Approach:**
Add one queued high-priority feature file in the existing format and place its id directly after `add-wake-first-relay-delivery` on the board.

**Verification:**
Inspect the exact three-file diff and run the local workflow checker only; no feature tests or reviews.

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Direct-main docs exemption was denied by the configured applicability checker (`risk_not_low`), so work moved to isolated branch `feat/protected-behavioral-requirements-roadmap`.
- Clean-context redline verdict: BLUE; no boundaries, contract surfaces, watch paths, or checkpoints.
- Added the queued high-priority item and placed it immediately after urgent wake reliability.
- `apply_patch` failed with the machine-local Windows error 1327 for the roadmap edit; a deterministic exact-file PowerShell replacement was used instead.
- Verification: `git diff --check`; import-boundary report; redline verdict BLUE; workflow checker. No feature tests or reviews were run, per scope.

