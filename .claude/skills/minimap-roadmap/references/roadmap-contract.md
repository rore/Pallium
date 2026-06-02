# Roadmap Contract

## Discovery

1. Check for `roadmap.config.json` at the repo root.
2. If it exists, read `roadmapPath` and resolve it relative to the repo root.
3. If it does not exist, use `roadmap/`.
4. Do not guess alternate paths when the configured location is missing.

## Ownership

Within the resolved roadmap root:

- `board.md` owns group names and item order
- `scope.md` owns the current-focus narrative
- `features/*.md` owns committed or active work
- `ideas/*.md` owns uncommitted or parked ideas

Do not create parallel roadmap trackers outside this structure unless the user explicitly asks.

## Item Files

Each item is a markdown file with YAML frontmatter.

Required frontmatter: `id`, `title`, `status`, `priority`, `commitment`.
Optional common: `milestone`.

Expected sections: `Summary`, `Why`, `In Scope`, `Out of Scope`, `Done When`, `Notes`. Additional sections are allowed.

When editing items:

- change `status`, `priority`, `commitment`, `title`, and `milestone` in frontmatter, not only in prose
- preserve unknown frontmatter keys and unknown markdown sections; keep section order unless the user asks for reorganization
- keep `id` stable unless the user explicitly asks to rename and update all references
- markdown inside sections is normal — don't flatten it
- if the structured editor doesn't fit the file cleanly, prefer a valid raw markdown edit over inventing a second schema

## Board

`board.md` shape:

```md
# Now
- feature-a
- feature-b

# Next
- feature-c

# Ideas
- idea-a
```

- group headings are freeform; pick what fits the repo (status, milestone, stream, …). `Now`/`Next`/`Ideas` are examples, not required.
- bullet order is canonical display order within each group
- bullet values are canonical item ids
- titles and badges come from item files, not from `board.md`
- preserve empty groups when they're meaningful structure
- update `board.md` only when grouping or ordering changes

## Scope

Use `scope.md` for short current-focus narrative and near-term direction. Item state belongs in item files, not in scope.

## Constraints

- no UI-only roadmap state, no separate database, no sync source
- do not move items between `features/` and `ideas/` unless the user asks for that semantic change
- if a file is malformed, surface the problem instead of rewriting it blindly
- raw item edits must still parse and must preserve the canonical item id

## Edit Order

1. Read the relevant roadmap files first.
2. Change the smallest set of files that own the requested truth.
3. Group/order changes → `board.md`. Focus narrative → `scope.md`. Item state → item file frontmatter and sections.
