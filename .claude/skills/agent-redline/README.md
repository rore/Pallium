# agent-redline (packaged skill)

This directory is a self-contained [Agent Skills](https://agentskills.io)
package. Drop it into your harness's skills directory:

| Harness | Install path |
|---|---|
| Claude Code (personal) | `~/.claude/skills/agent-redline/` |
| Claude Code (project) | `<your-repo>/.claude/skills/agent-redline/` |
| Codex / Cursor / Gemini CLI / others | See the harness's own docs |

Then start a session. The skill activates when you ask to set up
agent-redline in a repo, or when you work in a repo that already has
`agent-policy.yaml` at the root.

## Layout

```
agent-redline/
├── SKILL.md                            # entry (Agent Skills standard)
├── bootstrap-mode.md                   # one-time setup instructions
├── operating-mode.md                   # everyday loop
├── references/per-checkpoint/          # detail docs the agent loads on demand
├── assets/templates/                   # files bootstrap copies into consuming repos
├── assets/schema/                      # agent-policy.yaml + boundary-violations.json schemas
├── scripts/agent-redline-report.py     # the reporter (vendored into consuming repos)
└── extensions/
    ├── spring-archunit/                # JVM/Spring + ArchUnit (junit-xml output)
    └── python/                         # Python services + libraries + import-linter
                                        # (json-violations output via scripts/run-import-linter.py)
```

This package is generated from the agent-redline source repo
(<https://github.com/rore/agent-redline>) by `scripts/package-skill.sh`.
