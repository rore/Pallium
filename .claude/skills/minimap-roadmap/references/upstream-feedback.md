# Upstream feedback

Load this file only after the skill points here because Minimap's documented workflow failed or contradicted itself. Produce at most one upstream report per task.

## Qualifying triggers

- A documented Minimap instruction failed after its stated preconditions were met.
- Two Minimap instructions contradicted each other, or a referenced file, anchor, command, or route was missing.
- The CLI, HTTP API, server lifecycle, or roadmap behavior contradicted the shipped documentation.
- The same Minimap step required at least two retries for the same reason.
- Missing Minimap guidance forced a consequential guess.

Do not report expected states such as a surfaced stale or ambiguous anchor, target-repository or target-document problems, user permission denials, one-off environment failures, cosmetic preferences, or disagreement with deliberate policy.

## Filter

All three answers must be yes:

1. **Repeatable:** would another agent plausibly hit this on another task?
2. **Actionable:** can you name the affected Minimap file, instruction, command, route, or behavior?
3. **Upstream-owned:** does the fix belong in `rore/minimap`, rather than the target repository, local environment, or agent runtime?

If any answer is no, do not file. Briefly tell the user what happened only when it affects their task.

Host-agent orchestration, skill dispatch, and session coordination belong to agent-workflow. Relay, Session History, and derived memory belong to Pallium. Follow those projects' reporting workflows instead of filing them in `rore/minimap`; if ownership is mixed, isolate the Minimap-owned boundary or do not file.

## Privacy and duplicates

Never include raw prompts, transcripts, target-file content, repository or organization identity, credentials, secrets, personal data, or absolute local paths. Use the smallest sanitized error excerpt and a generic reproduction.

Before drafting, search open and closed issues:

```bash
gh issue list --repo rore/minimap --state all --search '<keywords> in:title' --limit 10
```

If an existing issue matches, link it and stop. Do not create or comment on a duplicate unless the user asks.

## Report

Title: `field-feedback: <specific failure>`

Body (at most 200 words):

```markdown
**Trigger:** <qualifying trigger>

**Affected surface:** <skill file/section, command, route, or behavior; source commit/version if known>

**Expected:** <documented result>

**Actual:** <sanitized result>

**Minimal reproduction:** <generic steps and bounded evidence>
```

Show the sanitized draft and obtain the user's approval before publishing unless the active user explicitly authorized automatic upstream reporting. Then file with `gh issue create --repo rore/minimap`. If GitHub CLI, authentication, access, or approval is unavailable, return the complete unsent draft in the task result and continue the user's task.
