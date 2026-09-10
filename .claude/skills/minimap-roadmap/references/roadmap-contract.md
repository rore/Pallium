# Roadmap Contract

## Discovery

1. Check for `roadmap.config.json` at the repo root.
2. If it exists, read `roadmapPath` and resolve it relative to the repo root.
3. If it does not exist, use `roadmap/`.
4. Do not guess alternate paths when the configured location is missing.

An optional top-level `defaultLens` in `roadmap.config.json` selects the initial metadata grouping. A valid URL `lens` wins, including explicit `lens=board`; without one, a valid `defaultLens` wins, then Board. Unknown URL or configured values fall back safely with a warning.

Filters use the common planning fields `status`, `priority`, `commitment`, `kind`, `milestone`, `lane`, and `labels` when each has two to eight distinct values. Add repo-specific frontmatter keys with `filters.fields`; fields configured under `lenses.fields` are also filterable. Explicitly configured fields may have more than eight values. `id` and `title` remain search-only.

## Ownership

Within the resolved roadmap root:

- `board.md` owns group names and item order
- `scope.md` owns the current-focus narrative
- `features/*.md` owns committed or active work
- `ideas/*.md` owns uncommitted or parked ideas

Metadata owns classification fields such as lane, milestone, and status. `board.md` owns one shared traversal order. Moving an item between metadata groups changes metadata only and retains that board position. Reordering in a metadata view uses visible neighboring items as before/after anchors in the canonical order, preserving hidden items; it must not silently cross freeform board groups. Use one neutral `Items` group when full cross-group prioritization is required. Metadata group order is configured by `lenses.fields.<field>.order`, not by board headings.

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

## Manual Metadata-First Migration

1. Check that the installed `minimap-roadmap` skill documents `defaultLens`; update the packaged skill before using the new key.
2. Inventory each board heading and the intended metadata field, then list every disagreement. Ask the developer to resolve conflicts; never guess which value wins.
3. Keep the chosen classification in item frontmatter. Preserve item ids, content, unrelated metadata, and feature/idea location.
4. Flatten existing board bullets in their current traversal order into one neutral `# Items` group. Do not add missing or unlisted items implicitly.
5. Configure `defaultLens` and `lenses.fields.<field>.order`, then reopen List view and verify filters and ordering. Moving an item to Unassigned must remove the grouped field, not write a placeholder value.

There is no automatic migration or board-to-metadata synchronization.
## Constraints

- no UI-only roadmap state, no separate database, no sync source
- do not move items between `features/` and `ideas/` unless the user asks for that semantic change
- if a file is malformed, surface the problem instead of rewriting it blindly
- raw item edits must still parse and must preserve the canonical item id

## Edit Order

1. Read the relevant roadmap files first.
2. Change the smallest set of files that own the requested truth.
3. Group/order changes → `board.md`. Focus narrative → `scope.md`. Item state → item file frontmatter and sections.

## Completion Reconciliation

Reconcile the affected canonical roadmap; a shipped note alone does not correct stale instructions. Make no edit where the roadmap is already accurate.

1. Update the owning item’s status and clearly distinguish shipped scope from remaining work; preserve useful completion evidence.
2. Remove or rewrite obsolete next-step claims that still tell the next agent to implement completed work.
3. Adjust board placement or order only where needed under the existing grouping and priority convention.
4. Check dependency statements directly affected by the completed slice.

Preserve unfinished or deferred scope honestly. If independently prioritized residual work remains under an umbrella item, propose a split; do not automatically split or reorder unrelated work.
