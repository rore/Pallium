# Hermes Relay qualification adapter

This is a Windows-only disposable, frozen-profile qualification adapter for Hermes v0.22.2. It
is not a general Hermes deployment integration. The qualification harness must
verify the actual loaded-plugin inventory and the request received by a local
provider stub. Competing llm_execution middleware, other providers, classic
CLI injection, multiple profiles, and automatic recovery after an uncertain
enqueue or claim remain unsupported. The native qualification is limited to
the frozen, disposable Windows profile described below; it does not establish
general compatibility.

The public pre_llm_call hook receives Hermes session_id and turn_id. The
adapter first polls only the payload-free pending-candidate endpoint, stores a
profile/container/session/endpoint/delivery metadata fence, and injects a
delivery-id/nonce wake marker. On the exact marker's actual turn, the hook
claims with register_session: false and returns the full attributed delivery
as request-only user context. llm_execution checks that the same marker and
full context reached the current user message, forwards the request, and ACKs
only after the provider call succeeds. The provider never performs Relay state
changes. A delivery is limited to 1600 payload characters and 2400 characters
including its attribution context. Oversized deliveries are refused. An
uncertain enqueue or claim fence blocks blind retry; recovery is not qualified.
Hermes emits on_session_end after each turn, so registrations remain available
for later idle turns and are removed only when the plugin unloads.

Copy this directory to $HERMES_HOME/plugins/pallium-hermes-relay/. Configure
an isolated Hermes profile with one enabled plugin and a loopback custom model
stub. Replace both example ports and container scope with the disposable
qualification values:

    plugins:
      enabled:
        - pallium-hermes-relay
      entries:
        pallium-hermes-relay:
          allow_gateway_injection: true
          settings:
            experimental_frozen_local_stub: true
            service_url: http://127.0.0.1:29999
            container_ref: git:example.test/team/hermes-e2e

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

The plugin refuses startup unless the profile explicitly opts into this frozen
experiment, enables exactly this plugin, explicitly selects the existing
`hermes-cli` toolset, selects a loopback custom provider, and has no fallback
provider/model. The unique reply tool joins that already-selected toolset;
this does not add a separate toolset or widen the profile's existing tool
selection. Tool Search must be explicitly disabled for this direct-tool
qualification because the native provider request must contain the reply tool
schema directly; the full Tool Search route is not qualified here. Quote
`"off"` in YAML so it remains Hermes' string enum. allow_gateway_injection: true is required
by Hermes for injection into an existing TUI/Desktop gateway session. The
`pallium_relay_reply` tool accepts only `delivery_id` and `payload`. A public
`tool_execution` middleware binds Hermes' trusted `session_id` and `turn_id` in
a plugin-local ContextVar only while the normal host dispatch runs. The
registered handler checks the bound turn against the admitted delivery and
the host-supplied session. The middleware calls the normal `next_call(args)`
path, preserving Hermes' authorization, hooks, and guardrails; other tools
pass through unchanged. The handler refuses calls without this scoped binding
because Hermes v0.22.2's ordinary registered-tool dispatch does not forward
`turn_id`.

Run the native test only with a clean checkout of the exact Hermes release
source (v0.22.2, commit d923a5eb487a17c0a68801bba9ef0f56c81040a8), a disposable
virtual environment with that release's [web] dependencies, and an isolated
HERMES_HOME/profile plus loopback Relay/provider stubs. Reuse an existing
interpreter read-only; do not install or alter global tools or configuration.
Set HERMES_E2E_SOURCE to that pinned source tree and HERMES_E2E_PYTHON to the
disposable environment's Python executable, then run:

    python -m pytest -m slow -q -n 0 tests/test_hermes_relay_native_e2e.py

An optional disposable pytest base directory can be supplied with
--basetemp <temporary-directory>. The test exercises an actual Hermes host;
the source-function qualification probe alone does not.

Only a successful local-provider-stub E2E run with the actual loaded inventory
and Relay state checks establishes this narrow qualification. It does not
qualify other Hermes releases, providers, middleware arrangements, restart
recovery, or production use.
