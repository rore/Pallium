# Minimap Contract

Minimap is a tiny repo-local, file-based roadmap and feature planning workspace for humans and agents.

The roadmap files in the repo are the only source of truth. Git is the history. The UI is only a structured lens and editor over those files.

## What Minimap Is

- a local roadmap and feature planning workspace stored in repo files
- a simple file convention that both humans and agents can follow
- a local UI for reading and editing those files
- a skill/instruction set for agents working with the same files

## What Minimap Is Not

- not a hosted planning service
- not a database-backed tracker
- not a second system of record
- not a workflow engine or automation platform
- not a Jira replacement

## Canonical Rules

1. Files are canonical.
   - The UI must never maintain separate roadmap state.
   - Agents and humans must update the same files.
2. Git is the history.
   - Do not build a separate history system into minimap.
3. The package is repo-local.
   - It can be copied into any repo and run there.
4. The package stays thin.
   - Prefer simple file editing and clear ownership over more machinery.

## Roadmap Root Discovery

Use the repo root as the starting point.

- If `roadmap.config.json` exists at the repo root, read `roadmapPath` and resolve it relative to the repo root.
- If it does not exist, use `roadmap/`.
- If the configured path is missing or invalid, surface a setup error instead of guessing.

Example config:

```json
{
  "roadmapPath": "docs/roadmap"
}
```

## Canonical File Ownership

Within the resolved roadmap root:

- `board.md` owns visible groups and ordered item ids
- `scope.md` owns the current-focus narrative
- `features/*.md` owns active or committed roadmap work
- `ideas/*.md` owns parked or uncommitted roadmap ideas

## Board Contract

`board.md` is a simple grouped list of item ids.

Example:

```md
# Now
- feature-a
- feature-b

# v2
- feature-c

# Ideas
- idea-a
```

Rules:

- headings are freeform and chosen by the repo
- headings may represent status, milestone, release, stream, team, or any other planning model
- bullet order is canonical display order within the group
- bullet values are canonical item ids
- titles and badges come from item files, not from `board.md`

## Item Contract

Each roadmap item is a markdown file with frontmatter and markdown sections.

Required core frontmatter:

- `id`
- `title`
- `status`
- `priority`
- `commitment`

Optional common frontmatter supported by minimap v1:

- `milestone`

Required core sections expected by minimap v1:

- `Summary`
- `Why`
- `In Scope`
- `Out of Scope`
- `Done When`
- `Notes`

Additional sections are allowed. Minimap keeps them in file order and surfaces them in the structured editor when they already exist.

Example:

```md
---
id: feature-a
title: Example feature
status: queued
priority: medium
commitment: committed
milestone: v1
---

## Summary

...

## Why

...

## In Scope

...

## Out of Scope

...

## Done When

...

## Notes

...

## Decision Locks

...
```

Markdown is allowed inside every section. Minimap does not require rich-text formatting or a separate document model.

## Preservation Rules

When minimap edits an item file, it should preserve:

- unknown frontmatter keys already present in the file
- unknown markdown sections already present in the file
- item ids unless the user explicitly asks to rename them and update references

## Editor Modes

Minimap v1 supports three item-editing modes:

- `Structured` for common metadata and known sections
- `Preview` for rendered markdown review before save
- `Raw` for full-file editing when a repo uses richer item files

Raw edits must still parse correctly and must preserve the item id.

## Human and Agent Collaboration Model

Humans use minimap through the local UI.
Agents use minimap through the file convention and the minimap skill.

Both operate on the same roadmap state.

That means:
- no hidden UI-only metadata
- no hidden agent-only tracker files
- no status changes only in prose if frontmatter owns the status

## Recommended v1 Boundary

Include:
- view board groups and item summaries
- read scope
- edit existing item metadata and sections
- preview item markdown before save
- edit full item markdown in raw mode
- reorder board groups

Do not assume in v1:
- database or hosted sync
- multi-user real-time collaboration
- arbitrary schema builders
- automation engine semantics tied to board headings
- rich workflow logic derived from UI state

## Package Contents

A copy-in minimap package should include:

- app/server files
- UI files
- roadmap parsing and save logic
- `SKILL.md`
- starter roadmap templates
- host-repo adoption notes
