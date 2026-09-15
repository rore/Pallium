# Optional Pallium participation

Pallium participation is separate from Minimap's file-backed roadmap. Use it only when the Pallium MCP work-reference tools are already available.

## When participation applies

Participate when you are explicitly assigned to implement the item or perform a substantive review that can change its deliverable. Passive reading, opening the UI, inspecting behavior, reordering a card, or making a clerical card edit is not participation.

Pallium's skill is helpful but not required when this reference and the callable work-reference tools are already available. Missing tools, an unavailable service, or an unavailable exact Minimap identity means continue the roadmap work without an association. Never install Pallium or use shell/HTTP substitutes.

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

- Read the authoritative item file, then derive its exact reference with the command above.
- Call `pallium_relay_work_refs` before attaching. Reuse an existing association with the same `scope_ref` and `local_ref`; otherwise call `pallium_relay_attach_work_ref` with that exact pair.
- If attach reports a capacity limit, do not detach or replace another association silently. Continue without the new association and report the result when it matters.
- Keep the association across turns. When you actually leave the work, call `pallium_relay_detach_work_ref` with the same pair. Detach only an explicit association you attached.
- On handoff, the receiving agent attaches itself. The sender detaches only when it has actually left the work.
- Treat the MCP result as authoritative. Never claim attachment or detachment succeeded without a successful result.
- Do not infer ownership, activity, acceptance, or completion from an association.
- If the tools are missing or unavailable, proceed without Pallium. Do not use a shell or HTTP substitute and do not install anything.

The optional Minimap server participant panel is read-only. Participant lookup uses `MINIMAP_PALLIUM_ENDPOINT`; exact-session links additionally require an explicitly configured, reviewed compatible `MINIMAP_PALLIUM_DASHBOARD_ENDPOINT`. Without that separate opt-in, or without a validated canonical endpoint, the name remains plain text. These panel settings do not control whether an agent may use already-available Pallium MCP tools.
