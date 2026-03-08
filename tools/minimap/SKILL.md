---
name: minimap
description: Use when reading, updating, or reorganizing roadmap state in a repo that uses the minimap file convention. Apply for roadmap planning and status changes; do not use for general engineering workflow unless the task is specifically about roadmap files.
---

# Minimap

## Intent

Use the minimap roadmap files as the canonical source of roadmap and feature planning truth for the repo.

The UI is only a human-friendly lens over those files. Agents and humans must operate on the same file state.

For the exact roadmap contract and package boundary, read `CONTRACT.md` in the same minimap package.

## Discovery

1. Check for `roadmap.config.json` at the repo root.
2. If it exists, read `roadmapPath` and resolve it relative to the repo root.
3. If it does not exist, use `roadmap/`.
4. Do not guess alternate paths when the configured location is missing.

## Ownership Rules

Within the resolved roadmap root:

- `board.md` owns group names and item order
- `scope.md` owns the current-focus narrative
- `features/*.md` owns detailed committed or active work
- `ideas/*.md` owns detailed uncommitted or parked ideas

Do not create parallel roadmap trackers outside this structure unless the user explicitly asks for them.

## Item Rules

Each roadmap item is a markdown file with YAML frontmatter.

Required core frontmatter:
- `id`
- `title`
- `status`
- `priority`
- `commitment`

Optional common frontmatter supported by minimap v1:
- `milestone`

Expected core sections:
- `Summary`
- `Why`
- `In Scope`
- `Out of Scope`
- `Done When`
- `Notes`

Additional sections are allowed.

When editing items:
- change status, priority, commitment, and title in frontmatter, not only in prose
- use optional common frontmatter like `milestone` in frontmatter when the repo uses it
- preserve unknown frontmatter keys if they already exist
- preserve unknown markdown sections if they already exist
- keep additional markdown sections in their original order unless the user explicitly wants them reorganized
- keep `id` stable unless the user explicitly asks to rename the item and all references

Markdown inside sections is normal and expected. Do not flatten markdown into plain text summaries.

If the structured editor does not fit the file cleanly, prefer a valid raw markdown edit over inventing a second schema.

## Board Rules

`board.md` uses this shape:

```md
# Now
- feature-a
- feature-b

# Next
- feature-c

# Ideas
- idea-a
```

Rules:
- headings are freeform board groups chosen by the repo
- repos can group by status, release, milestone, stream, team, or any other planning model
- `Now`, `Next`, and `Ideas` are examples, not required semantics
- bullet order is canonical display order within each group
- bullet values are canonical item ids
- titles and badges come from item files, not from `board.md`
- update `board.md` only when grouping or ordering changes

## Scope Rules

Use `scope.md` for short current-focus narrative and near-term direction.

Do not put item status changes only in `scope.md`. Item state still belongs in the item files.

## Constraints

- no UI-only roadmap state
- no separate database or sync source
- no hidden agent notes inside roadmap items unless the user explicitly wants that pattern
- do not move items between `features/` and `ideas/` unless the user asks for that semantic change
- if a file is malformed, prefer surfacing the problem over rewriting it blindly
- raw item edits must still parse and must preserve the canonical item id

## Recommended Agent Behavior

When a roadmap task is requested:
1. Read the relevant roadmap files first.
2. Change the smallest set of files that actually own the requested truth.
3. If group or order changes, update `board.md`.
4. If focus narrative changes, update `scope.md`.
5. If item state changes, update the item file frontmatter and relevant sections.
6. If the item uses extra sections or metadata, preserve them and edit them in place instead of normalizing them away.
7. Keep wording concrete and easy for both humans and agents to follow.
