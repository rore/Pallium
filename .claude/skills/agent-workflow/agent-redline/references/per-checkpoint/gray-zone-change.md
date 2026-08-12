# gray-zone-change

You're touching gray-zone code, or a `watch`-tagged path. The base rules are in `operating-mode.md`. This doc adds nuance specific to those two cases — they look similar in the PR comment but mean different things.

## Gray means "no zone matched"

Gray is the residual bucket. A file lands in gray when no `zones.red`, `zones.blue`, or `zones.watch` entry matches its path. Gray is a *tuning signal*: "this path hasn't been classified yet."

Right behavior when you touch gray:

- Proceed cautiously for *this* PR.
- Surface the gray-zone touch in the PR description.
- Suggest a policy update to classify the path explicitly — promote it to `red` (structural surface), `blue` (autonomous), or add it to `watch` (visible but not gating).

If you find yourself working in the same gray path repeatedly, the policy is incomplete. Don't keep working it as gray; classify it.

## Watch means "explicitly tagged for visibility"

`watch` is an *additive tag* a policy author placed on a path because they want it visible in PR comments regardless of how it's otherwise classified. A file can be:

- `red + watch` — structural surface, also flagged
- `blue + watch` — autonomous-by-default, but the reviewer still wants to see it change
- `gray + watch` — unclassified, and surfaced because the team knows this path matters

The key difference from gray: **`watch` is an intentional decision, gray is the absence of one.**

When you touch a `watch` path, no checkpoint fires (unless the path is also red). The reporter draws attention to it; the reviewer sees it changed; that's the entire mechanism. The PR description should briefly say what changed and why — short, factual, no ceremony.

## Don't escalate either to red unilaterally

Neither gray-zone code nor `watch`-tagged code requires a checkpoint by itself. If a specific change feels risky enough to deserve human attention, that's a signal about the *path* (it should be red), not about *this PR* (treat it as red ad-hoc). Surface the suggestion; don't reclassify mid-task.
