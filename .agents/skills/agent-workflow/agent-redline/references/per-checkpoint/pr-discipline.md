# pr-discipline

PR shape rules. The base PR description format is in `operating-mode.md` Step 6. This doc adds patterns to recognize and avoid when writing PR descriptions or shaping PRs.

## The audience is a 30-second skim

The reviewer reads the description in seconds, not minutes. Optimize for that. If your description requires the reviewer to spend more than 30 seconds before they can start reviewing the diff, it's too long.

## Bad descriptions to avoid

These patterns appear constantly in agent-generated PRs and signal slop:

- **The walkthrough.** Re-narrating each file's changes. The diff is the walkthrough; the description is what the diff doesn't say.
- **The history.** "First I tried X, then Y, then settled on Z." The reviewer doesn't need the journey; only the destination.
- **The restated requirement.** "We need to support multi-currency to handle international users..." That's the ticket, not the PR description. Link the ticket.
- **The future tense.** "This will allow..." The PR is past tense. State what it does.
- **The summary that summarizes the summary.** Repeat in different words for emphasis. Pick one phrasing.
- **The defensive prose.** "I considered Y but it would have caused..." Only relevant if there's a real risk the reviewer would propose Y. Otherwise cut.

## Good descriptions

The shape that survives the 30-second test:

- **What:** the smallest sentence that captures what changed. Two clauses max.
- **Why:** the smallest sentence that captures why. One clause is often enough; if you need two, the second is "and the existing approach didn't work because X."
- **Verification:** the commands you ran. One line each. Not a list of what you "verified" abstractly.

If a section needs more than three lines, the PR is probably doing too much.

## When you're tempted to write a long description

That's a signal the PR is too big. Symptoms:

- The "what" needs three clauses
- The "why" requires explaining background
- The verification list runs past five items
- You feel the need to defend the approach in the description

In each case, the right response is to split the PR, not to expand the description.

## Don't repeat what tools surface

The reporter's PR comment surfaces classification, checkpoints, boundary results, and PR size. Don't re-state any of that in your description. The reviewer sees both.
