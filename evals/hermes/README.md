# Hermes feasibility probes

This is an isolated investigation for
[`add-hermes-agent-integration`](../../roadmap/features/add-hermes-agent-integration.md),
not a production plugin or a qualified Hermes integration. It neither contacts
Pallium nor installs or starts Hermes. No model request is made.

The probe executes selected **actual released source functions** in fixture
namespaces. Source hashes are checked before execution. A fixture registry and
middleware manager replace the surrounding host. Results therefore establish
function-level semantics only; they do not prove a running Hermes host supplies
the right identity, profile, lifecycle, or provider request.

## Reproduce without installing Hermes

Use the existing repository Python environment. Download only the two inspected
source files from Hermes **v0.22.2**, exact revision
`d923a5eb487a17c0a68801bba9ef0f56c81040a8`, into a disposable directory:

```powershell
$hermesProbeSource = Join-Path ([IO.Path]::GetTempPath()) ("pallium-hermes-probe-" + [guid]::NewGuid())
$hermesProbeRevision = 'd923a5eb487a17c0a68801bba9ef0f56c81040a8'
foreach ($hermesProbeFile in @('tools/registry.py', 'hermes_cli/middleware.py')) {
    $hermesProbeResponse = gh api "repos/NousResearch/hermes-agent/contents/${hermesProbeFile}?ref=$hermesProbeRevision" | ConvertFrom-Json
    $hermesProbePath = Join-Path $hermesProbeSource $hermesProbeFile
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($hermesProbePath))
    [IO.File]::WriteAllBytes($hermesProbePath, [Convert]::FromBase64String($hermesProbeResponse.content))
}
python -m evals.hermes.qualification --source-root $hermesProbeSource
```

Source acquisition uses GitHub CLI read access. The probe itself is offline and
uses Python's standard library. A mismatch or missing source must fail before any
upstream function is executed. The output must identify its evidence level and
must never declare `qualified_host: true`.

## Questions the first slice can answer

- Does the registry preserve separately supplied host session/turn context across
  concurrent dispatches, even when model arguments contain forged identity keys?
- Are missing trusted context and a legacy narrow handler distinguishable without
  inferring identity from model arguments?
- Can execution middleware rewrite or short-circuit a request after an earlier
  observation? Do downstream errors and wrapper errors cause duplicate terminal
  execution?

These are synthetic calls into genuine source functions. The actual host callsite
is separate source-inspection evidence:
[`invoke_tool`](https://github.com/NousResearch/hermes-agent/blob/d923a5eb487a17c0a68801bba9ef0f56c81040a8/agent/agent_runtime_helpers.py#L2547-L2625)
constructs dispatch context from its owning agent. The executable registry probe
uses synchronous fixture handlers in concurrent threads. The inspected host
callsite is the concurrent tool executor; other host paths and async handlers
still need qualification. It supplies session/turn IDs but no explicit profile ID.

Initial local result: all eight pinned-source checks passed; six focused test
cases passed with `PALLIUM_HERMES_SOURCE_ROOT` supplied to pytest. The output
remains `source_function_probe` with `qualified_host: false`. Source acquisition,
actual host qualification and the repository's full-suite gate are separate.

```powershell
# Set only in this test process; do not persist it as a user environment variable.
$env:PALLIUM_HERMES_SOURCE_ROOT = $hermesProbeSource
python -m pytest --noconftest -q -n 0 tests/test_hermes_qualification.py
```

## Remaining gates

- Public per-call profile/container binding under concurrent routed profiles.
- The real plugin-to-tool path, including sequential and concurrent execution,
  empty/missing identity, reset, tool schemas and host lifecycle.
- Exact attributed payload inclusion at a defensible admission boundary. An
  `llm_execution` verifier's own input can still be rewritten or short-circuited
  downstream; an earlier observer or a successful wrapper return is insufficient.
- Actual-host model-stub and restart qualification, followed by shared integration
  against the relevant merged Relay reliability contracts.

The probes do not implement claim/ACK, wake polling, durable fencing, or any
unsupported-runtime fallback. Those remain owned by the feature's later slices.
