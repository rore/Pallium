# Configuration

This page explains Pallium's local configuration surface today.

Use it when you need to:

- choose between `demo_agent_memory` and `agent_conversation_memory`
- wire a live LLM provider
- override prompt variants or role-specific prompt behavior
- enable debug observability
- tune retention behavior

## Configuration Sources

Pallium reads configuration from four layers, in this order:

1. code defaults in `app/config.py`
2. `pallium.local.toml`
3. `.env.local`
4. real process environment variables

Later layers win over earlier layers.

Two path overrides also exist:

- `PALLIUM_ENV_FILE`
  - choose a different env file instead of `.env.local`
- `PALLIUM_CONFIG_FILE`
  - choose a different TOML file instead of `pallium.local.toml`

## Recommended Split

Use:

- `pallium.local.toml`
  - package structure
  - provider blocks
  - storage path
  - observability
  - retention
  - package prompt defaults
- `.env.local`
  - secrets
  - one-off local overrides

This matches the shipped config model and avoids hiding meaningful package behavior in flat env vars.

## Minimal Local Setups

### Demo Mode

Use this when you want to run Pallium without a live provider first.

```toml
default_use_case = "demo_agent_memory"

[storage]
backend = "sqlite"
sqlite_url = "sqlite:///./pallium.db"
```

### Live `agent_conversation_memory`

```toml
default_use_case = "agent_conversation_memory"

[storage]
backend = "sqlite"
sqlite_url = "sqlite:///./pallium.db"

[llm_providers.openai]
kind = "openai_compatible"
base_url = "https://api.openai.com/v1"
api_key_env = "PALLIUM_OPENAI_API_KEY"

[semantic_packages.agent_conversation_memory]
implementation = "agent_conversation_memory"
llm_provider = "openai"
model = "gpt-5-mini"
prompt_variant = "strict_typed_memory_v6_work_state_examples"
```

And in `.env.local`:

```dotenv
PALLIUM_OPENAI_API_KEY=your-key
```

## TOML Structure

Current top-level sections:

- `default_use_case`
- `[storage]`
- `[observability]`
- `[retention]`
- `[llm_providers.<name>]`
- `[semantic_packages.<name>]`
- `[semantic_packages.<name>.consolidation]`
- `[semantic_packages.<name>.prompt_variants]`

## Storage

```toml
[storage]
backend = "sqlite"
sqlite_url = "sqlite:///./pallium.db"
```

Current shipped backend:

- `sqlite`

## Observability

```toml
[observability]
integration_debug = true
```

This enables the local integration debug logger used by the service runtime.

Equivalent env override:

```dotenv
PALLIUM_OBSERVABILITY_INTEGRATION_DEBUG=true
```

## Retention

```toml
[retention]
enabled = false
run_interval_seconds = 300
lease_seconds = 300
batch_size = 200
```

Equivalent env overrides:

- `PALLIUM_RETENTION_ENABLED`
- `PALLIUM_RETENTION_RUN_INTERVAL_SECONDS`
- `PALLIUM_RETENTION_LEASE_SECONDS`
- `PALLIUM_RETENTION_BATCH_SIZE`

## Provider Blocks

Provider blocks live under `llm_providers`.

Example:

```toml
[llm_providers.openai]
kind = "openai_compatible"
base_url = "https://api.openai.com/v1"
api_key_env = "PALLIUM_OPENAI_API_KEY"
timeout_seconds = 30
max_attempts = 3
base_backoff_ms = 250
max_backoff_ms = 3000
jitter_ratio = 0.2
max_concurrency = 4
```

Supported fields today:

- `kind`
- `base_url`
- `api_key`
- `api_key_env`
- `timeout_seconds`
- retry policy:
  - `max_attempts`
  - `base_backoff_ms`
  - `max_backoff_ms`
  - `jitter_ratio`
  - `max_concurrency`

Provider-scoped env overrides use:

```dotenv
PALLIUM_PROVIDER__OPENAI__KIND=openai_compatible
PALLIUM_PROVIDER__OPENAI__BASE_URL=https://api.openai.com/v1
PALLIUM_PROVIDER__OPENAI__TIMEOUT_SECONDS=30
```

## Semantic Packages

Semantic packages live under `semantic_packages`.

Example:

```toml
[semantic_packages.agent_conversation_memory]
implementation = "agent_conversation_memory"
llm_provider = "openai"
model = "gpt-5-mini"
prompt_variant = "strict_typed_memory_v6_work_state_examples"
resolver_enabled = true
resolver_timeout_ms = 800
```

Supported package fields today:

- `implementation`
- `llm_provider`
- `model`
- `prompt_variant`
- `resolver_enabled`
- `resolver_timeout_ms`
- `consolidation`
- `prompt_variants`

Package-scoped env overrides use:

```dotenv
PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__MODEL=gpt-5-mini
PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__PROMPT_VARIANT=strict_typed_memory_v6_work_state_examples
PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__RESOLVER_ENABLED=true
PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__RESOLVER_TIMEOUT_MS=800
```

## Prompt Variants

There are two prompt controls:

- `prompt_variant`
  - package-wide default prompt variant
- `prompt_variants`
  - role-specific overrides

Resolution order is:

1. `prompt_variants[role]`
2. package `prompt_variant`
3. role-local code default

Example:

```toml
[semantic_packages.agent_conversation_memory]
prompt_variant = "strict_typed_memory_v6_work_state_examples"

[semantic_packages.agent_conversation_memory.prompt_variants]
query_ambiguity_resolution = "qar_v1_compact_contract"
```

Equivalent env override:

```dotenv
PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__PROMPT_VARIANTS__QUERY_AMBIGUITY_RESOLUTION=qar_v1_compact_contract
```

Use `prompt_variant` when you want the package default.

Use `prompt_variants` when only one prompt-backed role should diverge, for example:

- `query_ambiguity_resolution`

## Current Defaults

Code defaults today are:

- `default_use_case = "demo_agent_memory"`
- `llm_agent_memory.prompt_variant = "strict_typed_memory_v5_compact_examples"`
- `agent_conversation_memory.prompt_variant = "strict_typed_memory_v6_work_state_examples"`
- `agent_conversation_memory.resolver_enabled = true`
- `agent_conversation_memory.resolver_timeout_ms = 800`

The resolver prompt default is role-owned and currently resolves to:

- `qar_v1_compact_contract`

unless a role-specific override is configured.

## Legacy Compatibility

Older flat env vars still work as fallback inputs:

- `PALLIUM_LLM_PROVIDER`
- `PALLIUM_LLM_MODEL`
- `PALLIUM_LLM_BASE_URL`
- `PALLIUM_LLM_API_KEY`
- `PALLIUM_LLM_PROMPT_VARIANT`
- `PALLIUM_LLM_TIMEOUT_SECONDS`

When used, they create one legacy provider block and apply it to:

- `llm_agent_memory`
- `agent_conversation_memory`

Prefer the structured provider/package config instead.

## Common Recipes

### Switch to demo mode

```toml
default_use_case = "demo_agent_memory"
```

### Enable integration debug logs

```toml
[observability]
integration_debug = true
```

### Disable query ambiguity resolution

```toml
[semantic_packages.agent_conversation_memory]
resolver_enabled = false
```

### Override only the query ambiguity prompt

```toml
[semantic_packages.agent_conversation_memory.prompt_variants]
query_ambiguity_resolution = "qar_v1_compact_reasons"
```

### Change the SQLite file

```toml
[storage]
sqlite_url = "sqlite:///./tmp/pallium-dev.db"
```

## Troubleshooting

### My prompt change did not take effect

Check, in order:

- role-specific override in `prompt_variants`
- package `prompt_variant`
- `.env.local`
- real environment variables

Also see the prompt workflow note:

- [docs/context/prompt-improvement.md](context/prompt-improvement.md)

### I changed the code default, but local runs still use the old prompt

This often happens because `.env.local` still pins an override. The repo already records this lesson in:

- [docs/context/lessons.md](context/lessons.md)

### The package is configured, but no live LLM path is active

For `llm_agent_memory` and `agent_conversation_memory`, both must be present:

- `llm_provider`
- `model`

If either is missing, the plugin is not built as a live LLM-backed package.

## Read Next

- quick local setup: [getting-started.md](getting-started.md)
- integration flow: [agent-integration.md](agent-integration.md)
- API contract: [http-api.md](http-api.md)
- architecture truth: [context/architecture.md](context/architecture.md)
