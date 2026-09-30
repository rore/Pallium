# gray-zone-change

You're touching gray-zone code, or a `watch`-tagged path. The base rules are in `operating-mode.md`. This doc adds nuance specific to those two cases — they look similar in the PR comment but mean different things.

## Gray means "no zone matched"

Gray is the residual bucket. A file lands in gray when no `zones.red`, `zones.blue`, or `zones.watch` entry matches its path. Gray is a *tuning signal*: "this path hasn't been classified yet."

Right behavior when you touch gray:

- Proceed cautiously for *this* PR.
- Surface the gray-zone touch in the PR description.
- When evidence supports it, propose a narrow `red` or `blue` classification, or an additive `watch` tag, for future work. Batch nonurgent suggestions; policy edits need human approval.

If the same gray path recurs, use new evidence to propose a narrow correction for future tasks; do not repeat a rejected proposal without new evidence. This task keeps its current floor and checkpoints.

## Watch means "explicitly tagged for visibility"

`watch` is an *additive tag* a policy author placed on a path because they want it visible in PR comments regardless of how it's otherwise classified. A file can be:

- `red + watch` — structural surface, also flagged
- `blue + watch` — autonomous-by-default, but the reviewer still wants to see it change
- `gray + watch` — unclassified, and surfaced because the team knows this path matters

The key difference from gray: **`watch` is an intentional decision, gray is the absence of one.**

When you touch a `watch` path, no checkpoint fires (unless the path is also red). The reporter draws attention to it; the reviewer sees it changed; that's the entire mechanism. The PR description should briefly say what changed and why — short, factual, no ceremony.

## Don't escalate either to red unilaterally

Neither gray-zone code nor a `watch` tag triggers a Redline checkpoint by itself. If new danger emerges, raise this task's Risk immediately and seek its required review; do not invent a policy checkpoint. Propose an evidence-backed zone change separately with human approval; this task keeps its original floor and checkpoints even after approval.
