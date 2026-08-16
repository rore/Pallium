---
id: fix-redline-self-protection-path-mismatch
title: Fix the redline self-protection path so the policy file is actually protected
status: queued
priority: medium
commitment: uncommitted
---

## Summary

`agent-redline-policy.yaml`'s red-zone "self-protection" entry uses
`path: "agent-policy.yaml"` (lines ~65-67), but the actual file on disk is named
`agent-redline-policy.yaml`. The glob therefore does NOT match the real filename, so the
policy file is **not actually self-protected** — edits to it are not caught by the red
`architecture-review` checkpoint, and the file itself falls through to the gray default in
its own classification.

## Why

The self-protection entry exists precisely so that changes to the governance source of
truth go through architecture-review (weakening zones/boundaries should be hard). Because
of the filename mismatch, that guard is silently inert: anyone can edit the policy file
without tripping the intended checkpoint. This was confirmed twice during vNext work — the
policy file classified gray (not red) on PR #27, and a clean-context reviewer verified the
glob mismatch.

## In Scope

- Update the self-protection red entry to match the real filename
  (`agent-redline-policy.yaml`), or add it alongside the legacy name, so editing the policy
  file trips the `architecture-review` checkpoint.
- Confirm the header comment (line ~1, "agent-policy.yaml — Pallium") and any other
  references (e.g. `CLAUDE.md`, `agent-workflow.yaml` `redlineVerdictPath`) are consistent
  with the real filename, or reconciled.

## Out of Scope

- Any other zone/boundary change (the `.agent-workflow/**` blue-list shipped in #27).
- Renaming the policy file itself (changing the filename is riskier than fixing the glob).

## Done When

1. Editing `agent-redline-policy.yaml` produces a red verdict with the `architecture-review`
   checkpoint (verified on a test diff), instead of gray.
2. Filename references across the repo are consistent (or the discrepancy is documented as
   intentional).

## Notes

Surfaced during `blue-list-agent-workflow-path` (#27); the clean-context reviewer confirmed
the mismatch (`agent-redline-policy.yaml` lines 65-67 self-protection vs the real filename).
Editing this file is itself governance-sensitive → the fix PR should expect the
architecture-review checkpoint once the path is corrected.
