# Minimap

Drop this folder into a repo and give that repo a shared planning surface for humans and agents.

Minimap is a tiny repo-local, file-based roadmap and feature planning workspace. The roadmap files are canonical, git is the history, and the UI is only a structured lens and editor over those files.

## Why Use It

Minimap came out of a simple real-world pattern: building projects together with AI agents and repeatedly managing roadmap state through conversation.

That works for a while, but it stays too loose. This package gives that collaboration model more structure:
- humans use the local UI
- agents follow the minimap skill and file convention
- both update the same canonical roadmap files

That keeps planning lightweight, local, and deterministic.

For the exact product boundary and file contract, read `CONTRACT.md`.

## What The Editor Gives You

The item editor is intentionally small, but it is not limited to a rigid form.

- `Preview` mode lets you read the item as markdown first
- `Edit` mode handles the common metadata and the core sections
- `Raw` mode lets you edit the full file when a repo uses richer metadata or extra sections

Markdown is allowed inside every section, and minimap preserves unknown frontmatter keys and extra markdown sections instead of flattening everything into one schema.

## Recommended Host-Repo Layout

```text
<repo>/
  tools/
    minimap/
      server.js
      package.json
      src/
      ui/
      SKILL.md
      CONTRACT.md
      templates/
  roadmap/
    board.md
    scope.md
    features/
    ideas/
```

## Basic Setup

1. Copy this folder into the target repo as `tools/minimap/`.
2. Copy `tools/minimap/templates/roadmap/` into the target repo as `roadmap/`, or merge it into an existing roadmap root.
3. If the repo wants a custom roadmap location, copy `tools/minimap/templates/roadmap.config.json` to the repo root as `roadmap.config.json` and edit `roadmapPath`.
4. From the target repo root, run:

```bash
node tools/minimap/server.js
```

The server uses the current working directory as the repo root, so it must be launched from the host repo root.

## Board Grouping

- `board.md` headings are freeform and repo-defined.
- Repos can group work by status, milestone, release, stream, team, or any other planning structure.
- `Now`, `Next`, and `Ideas` are only examples, not required section names.

## Agent Hookup

Add a short note to the host repo's `AGENTS.md` or equivalent:

```md
For roadmap planning and roadmap file updates, follow `tools/minimap/SKILL.md`.
```

## What Is Included

- local UI/server app
- roadmap parsing and file save logic
- minimap skill instructions
- starter roadmap templates
- canonical contract documentation

## What Is Not Included

- database
- hosted service
- separate sync layer
- hidden state outside repo files
