---
name: minimap-roadmap
description: Use when showing or updating roadmap state in a repo with the minimap roadmap convention (board.md, scope.md, features/, ideas/). Not for arbitrary spec review.
---

# Minimap Roadmap

Roadmap files are the source of truth. The UI is a lens; agents and humans operate on the same files.

## Quick Workflow

When the user asks to **see** the roadmap, give them a URL. When they ask to **edit** roadmap state, edit the files directly. Both paths share step 1.

### 1. Make sure the server is running

```bash
node <path-to-this-skill>/scripts/start-server.mjs
```

The launcher prints one line: `Minimap running at http://localhost:<port>` (just started) or `Minimap already running at http://localhost:<port>` (reused). Capture the port — default 4312, but the launcher falls forward if busy.

For status / stop / restart, see [references/server.md](references/server.md).

### 2a. Showing the roadmap

Build the URL with the active repo's absolute path and reply with it:

```text
http://localhost:<port>/#repo=<absolute-path-to-active-repo>&view=board
```

The active repo is the directory the user is working in. Always pass an absolute path — the same server can serve any repo, switching is just a URL change.

### 2b. Editing roadmap state

1. Find the roadmap root from `roadmap.config.json`, or use `roadmap/`.
2. Read the files that own the truth before editing.
3. Edit the smallest owning file set.
4. Preserve unknown frontmatter and sections.

When completed work affects a roadmap item, reconcile its state using [Completion Reconciliation](references/roadmap-contract.md#completion-reconciliation).

For metadata-first roadmaps, keep classification in item metadata and the single shared traversal order in `board.md`. A membership move changes only metadata; moving to Unassigned removes that field rather than writing a placeholder; a metadata reorder uses visible before/after neighbors, preserves filtered-out items, and cannot silently cross freeform board groups. Configure group order with `lenses.fields.<field>.order` and optionally set the top-level `defaultLens`. A valid URL lens, including `lens=board`, overrides that default; unknown values fall back with a warning. Do not perform automatic migration: check the installed skill version and follow the manual migration steps in [references/roadmap-contract.md](references/roadmap-contract.md).

For ownership rules, item shape, board rules, and edit constraints, read [references/roadmap-contract.md](references/roadmap-contract.md).

When explicitly implementing or substantively reviewing a known roadmap item, and only when Pallium MCP work-reference tools are available, follow [references/pallium-participants.md](references/pallium-participants.md). Pallium is optional: never install it, shell out to it, or block ordinary Minimap work when those tools are absent.

## Agent Handoffs

For assigned roadmap work, use the manager-designated shared checkout and make roadmap edits there; do not automatically sync changes across worktrees. On pickup or resume, confirm the canonical item id and read its current file and relevant roadmap state. On pause or handoff, report the exact item id and repository-relative item path (and exact Pallium `scope_ref`/`local_ref` when applicable), changed files, and current worktree state, including any uncommitted work. The receiving agent re-reads the item and attaches its own Pallium association when applicable; the sender detaches only an association it attached and only after leaving the work. On completion, reconcile the owning roadmap item under [Completion Reconciliation](references/roadmap-contract.md#completion-reconciliation) and report the resulting state and changed files. These notes do not transfer roadmap file ownership or imply an Agent Workflow requirement.

## Composing With Spec Review

A roadmap item is just a markdown file. To open a review thread on one item (anchored comments, suggestions), attach the item file via the `minimap-spec-review` skill if it is installed alongside this one. Spec sessions never auto-mutate the file, so the layers compose safely.

If only this skill is installed, the user can still drive the conversation through any other client (the running minimap server serves both modes).

## Guardrails

- Do not create parallel roadmap trackers.
- Do not treat chat as the source of truth when roadmap files exist.
- Always pass the absolute repo path in the URL hash; do not assume the running server is rooted in your repo.
- Do not curl the server, send signals, or edit `$MINIMAP_HOME/server.json` or its participant preference by hand. Use the bundled scripts only.
- If Minimap's documentation, CLI, HTTP API, server, UI, or lifecycle scripts fail or contradict documented behavior, load [`references/upstream-feedback.md`](references/upstream-feedback.md); otherwise do not load it.
