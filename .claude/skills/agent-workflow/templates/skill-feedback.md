# skill-feedback

Load this file only when a trigger from the [Skill feedback check](checkpoints/review-result.md#skill-feedback-check) fired during this task. Produces at most one issue against the source repo. Walk the filter first; only file if it passes.

## Actionability filter

Two questions. Both must be yes:

1. Would another agent hit this on a different task? (Repeatability — one-off situations don't earn an issue.)
2. Can you name the specific file, section, or missing instruction that should change? (Pointable cause — if you can't point at it, the report is a vent.)

If either is no, drop. Add a one-line note in the Work Record's Implementation prose: `Trigger <N> fired but did not pass the actionability filter: <reason>`. Then proceed to Review the Result close.

## Do NOT file for

| Category | Why not |
|---|---|
| Your own misread of the user's request | Not a skill defect. |
| One-off environment / tool flakes | Not repeatable. |
| Cosmetic gripes ("this prose feels stiff") | Not actionable. |
| Disagreement with deliberate policy (e.g., budget discipline, the non-waivable rules) | That's a feature request — open a discussion, not an issue. |
| Raw transcripts, CLAUDE.md/AGENTS.md content, credentials, or organizational instructions | Never include in an issue body — redact before filing. |

## Issue format

Title: `skill-feedback: <one-line summary of the suspected friction>`

Body (≤200 words, five fields):

```
**Trigger fired:** <number + name from the trigger list>

**What the skill said (or failed to say):** <quote the prose, or note "no instruction found">. File: `<path>` §<section>.

**What happened:** <one or two sentences — the concrete confusion, retry, or invalid artifact. Do not quote transcripts or organizational instructions verbatim.>

**Suggested fix:** <point at the specific section. E.g., "add to operating-mode.md §'The loop' a line that names X." Or "cross-reference review-result.md §Y to the predicate detail Z.">

**Work Record:** <commit SHA + path to .agent-workflow/tasks/<slug>.md in the consumer repo, if shareable. Include the skill source commit SHA if known: `git -C <skill-root> log -1 --format=%H`.>
```

Cap body at 200 words. Longer reports get triaged later or not at all.

## How to file

Source repo: `https://github.com/rore/agent-workflow`

```bash
gh issue create \
  --repo rore/agent-workflow \
  --title 'skill-feedback: <summary>' \
  --body-file <(cat <<'EOF'
**Trigger fired:** ...

**What the skill said (or failed to say):** ...

**What happened:** ...

**Suggested fix:** ...

**Work Record:** ...
EOF
)
```

If `gh` is not available or the source repo is not accessible from the consumer environment, record the would-be issue body in the Work Record under `## Skill feedback (unsent)` with the same five fields. A maintainer picking up the Work Record can transcribe it.

## After filing

Append to the Work Record's Implementation prose: `Skill feedback issue filed: <URL>`. One line. Then close Review the Result.
