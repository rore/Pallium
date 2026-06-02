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

For ownership rules, item shape, board rules, and edit constraints, read [references/roadmap-contract.md](references/roadmap-contract.md).

## Composing With Spec Review

A roadmap item is just a markdown file. To open a review thread on one item (anchored comments, suggestions), attach the item file via [`minimap-spec-review`](../minimap-spec-review/SKILL.md). Spec sessions never auto-mutate the file, so the layers compose safely.

## Guardrails

- Do not create parallel roadmap trackers.
- Do not treat chat as the source of truth when roadmap files exist.
- Always pass the absolute repo path in the URL hash; do not assume the running server is rooted in your repo.
- Do not curl the server, send signals, or edit `$MINIMAP_HOME/server.json` by hand. Use the bundled scripts only.
