---
name: minimap-roadmap
description: Use when reading, updating, or reorganizing roadmap state in a repo that hosts or uses the minimap roadmap file convention. Apply for roadmap planning and status changes; do not use for arbitrary spec review unless the user is using minimap-spec-review.
---

# Minimap Roadmap

## Intent

Use minimap roadmap files as the canonical source of roadmap and feature-planning truth for a repo.

The UI is only a lens over those files. Agents and humans must operate on the same file state.

## Quick Workflow

1. Find the roadmap root from `roadmap.config.json`, or use `roadmap/` when no config exists.
2. Start or verify the bundled server:
   `node <path-to-this-skill>/scripts/start-server.mjs`
   To check status, stop, or restart, use the matching scripts in the same directory (`status.mjs`, `stop-server.mjs`, `restart-server.mjs`). Do not curl the server, send signals, or edit `$MINIMAP_HOME/server.json` by hand.
3. Open the UI for *this repo*:
   `http://localhost:4312/#repo=<absolute-path-to-repo>&view=board`
4. Read the files that own the requested truth before editing.
5. Edit the smallest owning file set.
6. Preserve unknown metadata and sections.
7. Run the repo's normal validation if behavior or generated roadmap output could be affected.

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
