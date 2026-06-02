---
name: minimap-roadmap
description: Use when reading, updating, or reorganizing roadmap state in a repo that hosts or uses the minimap roadmap file convention. Apply for roadmap planning and status changes; do not use for arbitrary spec review unless the user is using minimap-spec-review.
---

# Minimap Roadmap

## Intent

Use minimap roadmap files as the canonical source of roadmap and feature-planning truth for a repo.

The UI is only a lens over those files. Agents and humans must operate on the same file state.

## Quick Workflow

When the user asks to see the roadmap, give them a URL. When they ask to edit roadmap state, edit the files directly. The two paths share step 1.

### 1. Make sure the server is running

```bash
node <path-to-this-skill>/scripts/start-server.mjs
```

Output is one line, either `Minimap running at http://localhost:<port>` (just started) or `Minimap already running at http://localhost:<port>` (reused). Either way, capture the port from that line. The default is 4312 but the launcher falls forward if busy. To check status, stop, or restart, use the matching scripts in the same directory (`status.mjs`, `stop-server.mjs`, `restart-server.mjs`). Do not curl the server, send signals, or edit `$MINIMAP_HOME/server.json` by hand.

### 2a. Showing the roadmap to the user

Build the URL with the active repo's absolute path and reply with it:

```text
http://localhost:<port>/#repo=<absolute-path-to-the-active-repo>&view=board
```

The active repo is the directory the user is working in (e.g. `process.cwd()` of the agent session, or the project root they're asking about). Always pass an absolute path. The same server can serve any number of repos — switching repos is just a URL change.

Tell the user the URL plainly. They don't need to know about the server, the port-fallback, or the registry.

### 2b. Editing roadmap state

For roadmap planning, status changes, or item updates, work on the files directly:

1. Find the roadmap root from `roadmap.config.json`, or use `roadmap/` when no config exists.
2. Read the files that own the requested truth before editing.
3. Edit the smallest owning file set.
4. Preserve unknown metadata and sections.
5. Run the repo's normal validation if behavior or generated roadmap output could be affected.

A single running minimap server can serve roadmap for any number of repos. The launcher detects an already-running instance and reuses it; switching repos in the UI means changing the `repo=` value in the URL.

## Collaborate On A Specific Item

A roadmap item is just a markdown file. To open a review thread on one specific item (anchored comments, suggestions, replies), attach the item file as a spec session via [`minimap-spec-review`](../minimap-spec-review/SKILL.md). The roadmap skill keeps managing the item's role in planning; the spec-review skill manages the conversation around its content. Spec sessions never auto-mutate the file, so the two layers are safe to use together.

## Load More When Needed

- For server lifecycle and discovery, read [references/server.md](references/server.md).
- For ownership rules, item structure, board rules, and edit constraints, read [references/roadmap-contract.md](references/roadmap-contract.md).
- When using this skill from the packaged minimap folder, `../../CONTRACT.md` contains the package-level product boundary.

## Guardrails

- Do not create parallel roadmap trackers.
- Do not treat chat as the source of truth when roadmap files exist.
- Do not use this skill for global arbitrary-file review; use `minimap-spec-review` for that.
- Always pass the absolute repo path in the URL hash; do not assume the running server is rooted in your repo.
