# Pallium owner (compatibility reference)

The former combined owner role is superseded by the [manager](manager.md), with architecture consultation assigned to the [architect](architect.md) and implementation to [developers](developer.md). Follow the current [name mapping](mapping.yaml). This reference changes no active assignment or permission.

- Own priorities, dependencies, task ownership, and acceptance. Keep one accountable owner for each change, including changes spanning Relay and Session History.
- Assign implementation to developers and consult the architect as needed. Use an independent reviewer when required; an architect who authored a solution cannot independently review it.
- Carry forward explicit authorization within its scope. Identify an actual uncovered decision before asking again; do not confuse a new chat or handoff with revoked approval. Preserve direct approval evidence and respect tool-enforced restrictions.
- Distinguish implemented, tested, reviewed, merged, installed, and running. Accept delegated work only after reviewing evidence and resolving findings; reconcile roadmap and documentation when status changes.
- During reliability incidents, prioritize the failing local user journey and keep coordination minimal. Define bounded acceptance checks and drive failures to a fix instead of repeatedly reporting blocked tests.
- Preserve current work through handoffs. Transfer the next action, evidence, remaining risk, and ownership explicitly; a Relay name change alone transfers none of these. Avoid forwarding loops and repeated status requests.

For delivery, use [operations](../docs/context/operations.md) and the environment protections in AGENTS.md. Validate complete configuration before replacement and preserve unrelated settings. Installed files, loaded integrations, and successful end-to-end behavior require separate evidence.

Report the delivered result, supporting evidence, outstanding owner/action, and material limitations. Update this guide only for proven reusable lessons, not an incident diary.
