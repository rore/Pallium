# Optional Pallium participation

Pallium participation is separate from Minimap's file-backed roadmap. Use it only when the Pallium MCP work-reference tools are already available.

## Get the exact item reference

Read the authoritative reference locally; do not recreate its escaping or repository identity rules:

```bash
node <skill>/runtime/cli.js roadmap item-ref <item-id> --repo <absolute-repo-path> --json
```

The result contains `scope_ref` and `local_ref`. It does not contact Pallium and still works when `MINIMAP_PALLIUM_ENDPOINT` is unset. If the command reports that repository identity is unavailable, continue the roadmap work without a Pallium association; do not guess from a local path, branch, or raw item id.

The versioned form is:

- `scope_ref`: `roadmap:v1:<canonical-credential-free-git-identity>#<encoded-repository-relative-roadmap-root>`
- `local_ref`: `item:v1:<encoded-item-id>`

Both encoded parts use NFC Unicode and RFC 3986 percent encoding. Minimap is the authority for the concrete values and bounds.

## Attach and detach

- When you explicitly take responsibility for working on the known item, call `pallium_relay_attach_work_ref` with the exact `scope_ref` and `local_ref`.
- When you leave that work, call `pallium_relay_detach_work_ref` with the same pair. Detach only an association you attached.
- Treat the MCP result as authoritative. Never claim attachment or detachment succeeded without a successful result.
- Viewing, opening, reviewing, reordering, or editing a card does not imply participation. Do not infer ownership, activity, acceptance, or completion from an association.
- If the tools are missing or unavailable, proceed without Pallium. Do not use a shell or HTTP substitute and do not install anything.

The optional Minimap server participant panel is read-only. Its endpoint configuration does not control whether an agent may use already-available Pallium MCP tools.