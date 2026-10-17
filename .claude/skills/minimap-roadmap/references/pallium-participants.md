# Optional Pallium participation

Pallium participation is separate from Minimap's file-backed roadmap. Use it only when the Pallium MCP work-reference tools are already available.

## When participation applies

Participate when explicitly assigned to implement, investigate, test, or substantively review a known roadmap item. Assigned investigation and testing qualify even when they do not change code or roadmap files. Passive reading, opening the UI, casual behavior inspection, reordering a card, or making a clerical card edit is not participation.

Pallium's skill is helpful but not required when this reference and the callable work-reference tools are already available. Missing tools, an unavailable service, or an unavailable exact Minimap identity means continue the roadmap work without an association. Never install Pallium or use shell/HTTP substitutes.

## Get the exact item reference

Use the shared [Feature references in handoffs](../SKILL.md#feature-references-in-handoffs) procedure to read the canonical item and resolve its exact tuple. The CLI does not contact Pallium and still works when `MINIMAP_PALLIUM_ENDPOINT` is unset. If identity is unavailable, continue the roadmap work without a Pallium association; do not guess from a local path, branch, or raw item id.

The versioned form is:

- `scope_ref`: `roadmap:v1:<canonical-credential-free-git-identity>#<encoded-repository-relative-roadmap-root>`
- `local_ref`: `item:v1:<encoded-item-id>`

Both encoded parts use NFC Unicode and RFC 3986 percent encoding. Minimap is the authority for the concrete values and bounds.

## Attach and detach

The board's Recent and quieter Dormant badges classify attached, nonclosed sessions under Pallium's inclusive 24-hour session last-seen window—not work on this feature, staffing, or completion. Total equals Recent plus Dormant; aliases and destination health do not classify recency. Legacy total-only batches leave classification unsupported rather than all-Recent, without N+1 fallback. Detail is a separate observation, not a shared board snapshot.

Use existing linked Pallium session controls for explicit association cleanup; Minimap performs no administration. Explicit detach removes only that origin, while structural origins require producer refresh. Close releases the alias and excludes the session from default participant reads but retains associations. Detach does not relabel captured History. Associations do not backfill earlier turns or guarantee historical participation, access, or coverage: per-turn lookup must succeed and History has a five-reference capture cap.

- Read the authoritative item file, then use the shared feature-reference procedure above.
- Call `pallium_relay_work_refs` before attaching. Reuse an existing association with the same `scope_ref` and `local_ref`; otherwise call `pallium_relay_attach_work_ref` with that exact pair.
- If attach reports a capacity limit, do not detach or replace another association silently. Continue without the new association and report the result when it matters.
- Keep the association across turns. When you actually leave the work, call `pallium_relay_detach_work_ref` with the same pair. Detach only an explicit association you attached.
- On handoff, the receiving agent attaches itself. The sender detaches only when it has actually left the work.
- Treat the MCP result as authoritative. Never claim attachment or detachment succeeded without a successful result.
- Do not infer ownership, activity, acceptance, or completion from an association.
- If the tools are missing or unavailable, proceed without Pallium. Do not use a shell or HTTP substitute and do not install anything.

The optional Minimap participant panel is read-only. With a validated loopback `MINIMAP_PALLIUM_ENDPOINT`, both visible board modes refresh observations independently through `GET /api/board/observations?snapshot=<id>`. The opened repository's snapshot manifest supplies validated references and ambiguity coverage without another Git scan. One bounded Pallium `POST /relay/work-refs/participant-counts` covers at most 200 references, with unfinished candidates before completed ones; there are no per-card count requests. Completed-item board badges appear only in In play; session detail remains available on demand. In play means normalized status `active` or `in-progress`, OR any confirmed attached, nonclosed session, including dormant sessions—not working right now. Overflow and error/unknown outcomes remain visibly incomplete, never zero; active and in-progress matches still appear. Roadmap validation and participant observations have separate timestamps. The UI adds `includeCompleted=1` only when In play can include completed statuses; ordinary observations omit completed candidates.

Across worktrees is a separate read-only board projection. Associations are feature-wide, never evidence that a particular checkout version is active. Independent features sharing an NFC-equivalent item ID receive no inferred count or participant detail. The new UI requests `participants=0` on worktree-workspace reads so provider lookup does not delay the board. Legacy requests without that flag still include a bounded count batch in the workspace response. Legacy `GET /api/board/participant-counts` also remains available: completed items are omitted by default, `includeCompleted=1` includes them, absent or `0` preserves the default, and invalid or repeated values are rejected. Successful completed-inclusive responses echo `includeCompleted: true`; an older server ignoring the flag leaves results incomplete.

The provisional `openedOnly=1` snapshot skips participant lookup until the full scan resolves feature identity. Its session status is loading/unknown, not zero, and feature totals and In play cover only the opened checkout. A failed full scan leaves this incomplete view usable with Refresh retry. Automatic roadmap reads can reuse a validated snapshot for 30 seconds; visible expired snapshots are validated again, while Manual Refresh always requests fresh validation.

Observation refresh stops and its pending request is cancelled when the page is hidden or Spec sessions is opened. Returning resumes visible refresh using a current manifest; an expired manifest triggers roadmap validation. Failed observations retain last successful counts with a stale or unavailable cue. Changing repository or read mode discards those observations. When lookup is disabled, Minimap makes no Pallium HTTP requests. Exact-session links separately require an explicitly configured, reviewed compatible `MINIMAP_PALLIUM_DASHBOARD_ENDPOINT`; without it, names remain plain text. These settings do not control whether an agent may use already-available Pallium MCP tools.
