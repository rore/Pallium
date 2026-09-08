# Upstream field feedback

Load this file only after observing a repeatable Pallium product, integration, contract, packaging, or documentation defect.

## Route

Use this workflow only when all are true:

- another agent, task, or supported runtime can repeat the behavior;
- the affected Pallium-owned behavior, file, contract, or documentation is pointable, with expected and actual results;
- an upstream change in `rore/Pallium` would fix it.

Drop one-off environment, tool, or network failures; downstream misuse; intentional policy disagreements; and reports that cannot be made actionable without private data.

A memory-quality miss—bad extraction, retrieval, ranking, relevance, or injection choice—belongs only in Pallium's existing `pallium_query_debug`, `pallium_flag_memory`, `pallium_rate_memory`, and feedback/replay mechanisms. Use this workflow only if that mechanism itself is defective.

## Draft safely

Draft before taking any external action. Use public evidence and the minimum context needed. Never include raw prompts, transcripts, injected or retrieved memory, secrets, credentials, private repository or organization names, local paths, session or user identifiers, log dumps, or organization instructions. Generalize the reproduction; if safe redaction makes it non-actionable, do not post it.

Use title `field-feedback: <summary>` and a body no longer than 200 words and 2,000 Unicode characters:

- **Surface:** product, integration/runtime, contract/packaging, or documentation;
- **Trigger and repeatability:** minimal public-safe conditions;
- **Expected / actual:** one bounded comparison;
- **Redacted reproduction or evidence:** no private context;
- **Suggested upstream fix:** smallest useful direction.

Non-ASCII text is allowed after redaction and remains subject to both limits.

## Search and submit

1. Show the redacted draft to the user and ask for explicit approval before any GitHub search, issue creation, or comment.
2. Only after approval, search for duplicates through a process or tool API that passes arguments without a shell:

   `["gh", "issue", "list", "--repo", "rore/Pallium", "--state", "all", "--search", "<public-safe terms>", "--limit", "20"]`

3. If a duplicate exists, report its URL and do not create or comment unless separately approved.
4. Otherwise write the approved body to a private temporary file with a file API, then invoke without a shell:

   `["gh", "issue", "create", "--repo", "rore/Pallium", "--title", "field-feedback: <summary>", "--body-file", "<temp-file>"]`

Delete the temporary file afterward. Never interpolate draft, title, search, or path text into a shell command. If an argv-safe process call and safe file API are unavailable, use the unsent fallback.

If approval is withheld, `gh` is missing or unauthenticated, access is denied, the network fails, or submission is uncertain, do not retry blindly. Return the safe draft under `## Field feedback (unsent)` in the current Work Record when repository-safe; otherwise show it only to the user. Do not add telemetry, service APIs, or feedback storage.
