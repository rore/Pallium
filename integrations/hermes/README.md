# Pallium Relay for Hermes

This is a frozen, disposable-profile qualification package for Hermes v0.22.2. It installs a native Hermes plugin, the discoverable `pallium-memory` skill, and the plugin-owned Pallium MCP bridge. Setup never creates a global `mcp_servers` connection and does not modify model/provider, toolset, Tool Search, other plugin, credential, or data settings.

## Prepare an isolated profile

The setup command requires an existing explicit profile with the qualification settings already present. It refuses to repair or silently change them. The selected profile must have no other enabled plugin, select only the existing `hermes-cli` toolset, use a loopback custom provider with no fallback, and set Tool Search to the string value `"off"`:

```yaml
plugins:
  enabled: []
platform_toolsets:
  cli: [hermes-cli]
tools:
  tool_search:
    enabled: "off"
model:
  default: probe-model
  provider: custom
  base_url: http://127.0.0.1:57089/v1
  api_key: local-stub
  api_mode: chat_completions
fallback_providers: []
```

Use only a disposable `HERMES_HOME`, a loopback Pallium service, and a local provider stub. The installer calls the public Hermes config writer in the selected `--hermes-python` interpreter and refuses incompatible or unreadable profile config before touching package files.

Run setup and removal only while the target Hermes host and other profile config
writers are stopped. The digest check detects edits before writing; the native
writer provides no atomic compare-and-swap against overlapping external writes.
Concurrent config writers and production installation remain unqualified. On an
uncertain write, current config bytes are retained for inspection rather than
overwritten from an older snapshot.

## Install, inspect, and remove

From the Pallium checkout, pass the exact profile and both Python environments:

```powershell
python -m app.run setup hermes `
  --home C:\path\to\disposable-hermes-home `
  --hermes-python C:\path\to\hermes-venv\Scripts\python.exe `
  --service-url http://127.0.0.1:29999 `
  --container-ref git:example.test/team/hermes-e2e `
  --actor-ref hermes-e2e `
  --visibility private `
  --mcp-python C:\path\to\pallium-venv\Scripts\python.exe `
  --mcp-repo C:\path\to\Pallium
```

`--mcp-python` defaults to the current Pallium interpreter and `--mcp-repo` to this checkout. Setup validates Pallium MCP SDK v1 and Hermes MCP SDK v2 before mutation. The `service-url`, container, actor and visibility values are explicit package scope; this release accepts private visibility only.

Inspect configured files with the same explicit profile:

```powershell
python -m app.run setup hermes --home C:\path\to\disposable-hermes-home `
  --hermes-python C:\path\to\hermes-venv\Scripts\python.exe --status
```

Remove only unchanged package-owned files and configuration:

```powershell
python -m app.run setup hermes --home C:\path\to\disposable-hermes-home `
  --hermes-python C:\path\to\hermes-venv\Scripts\python.exe --uninstall
```

Setup is repeatable. The installer stores ownership fingerprints beside the plugin and skill. It refuses unowned collisions or edited owned artifacts rather than replacing them. Removal restores the original `plugins.enabled` state, deletes only this plugin's exact config entry, and preserves unrelated nested configuration and other enabled plugins. A conflict leaves the profile untouched. Status checks file/config fingerprints only; it does not qualify a running host or live MCP connection.

The profile skill is installed under `$HERMES_HOME/skills/pallium-memory/`, so Hermes includes it in normal skill discovery. History search and derived-memory tools are not exposed by this package. Relay hook deliveries own their claim and ACK; use the reply operation for an injected delivery and never receive or ACK it again.

## Native qualification limits

The native wake qualification remains limited to the pinned Hermes v0.22.2 source, explicit frozen local-provider profile, and loopback stubs. Run the focused host journey only with a clean pinned checkout and disposable Hermes environment:

```powershell
$env:HERMES_E2E_SOURCE = 'C:\path\to\pinned\hermes-agent'
$env:HERMES_E2E_PYTHON = 'C:\path\to\hermes-venv\Scripts\python.exe'
python -m pytest -m slow -q -n 0 tests/test_hermes_relay_native_e2e.py
```

This does not qualify other Hermes releases, remote providers, competing middleware, multiple-profile routing, recovery after uncertain enqueue/claim, or production use. It does not install into or alter a user's everyday Hermes profile.
