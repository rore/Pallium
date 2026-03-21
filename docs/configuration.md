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

[embedding_providers.onnx]
kind = "onnx"
model = "BAAI/bge-small-en-v1.5"

[vector_index]
enabled = true
index_path = "./pallium_vector.index"
embedding_provider = "onnx"
min_similarity = 0.55
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
- `[semantic_packages.<name>.model_roles]`
- `[embedding_providers.<name>]`
- `[vector_index]`

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
- `auth_style` — `"native"` (default) or `"bearer"` (for proxy endpoints)
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
PALLIUM_PROVIDER__OPENAI__AUTH_STYLE=bearer
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
- `model_roles`

Package-scoped env overrides use:

```dotenv
PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__MODEL=gpt-5-mini
PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__PROMPT_VARIANT=strict_typed_memory_v6_work_state_examples
PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__RESOLVER_ENABLED=true
PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__RESOLVER_TIMEOUT_MS=800
PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__MODEL_ROLES__WRITE_EXTRACTION=claude-sonnet-4-6
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

## Model Roles

There are two model controls:

- `model`
  - package-wide default model
- `model_roles`
  - role-specific model overrides

Resolution order is:

1. `model_roles[role]`
2. package `model`

Available roles:

- `write_extraction` — per-item memory extraction (quality-critical, use strongest model)
- `thread_aggregation` — thread summary + task checkpoint (simpler schemas, code has fallback defaults)
- `consolidation` — pattern and continuity memory (simplest schemas)
- `query_ambiguity_resolution` — resolver on query hot path (speed-critical, simple A/B decision)

Benchmarked recommendation (Anthropic Claude):

| Role | Model class | Rationale |
|---|---|---|
| `write_extraction` | Sonnet (default) | 14-field schema with strict evidence rules. Quality-sensitive — needs the strongest model. |
| `thread_aggregation` | Haiku | Simpler schema, code has fallback defaults. Benchmarked: 11/11 routing, 100% work resumption contract. |
| `consolidation` | Haiku | Simplest schemas. Same benchmark results as thread_aggregation. |
| `query_ambiguity_resolution` | Haiku | Hot path (800ms timeout), simple A/B decision. Speed matters more than depth. |

When using OpenAI or other providers, the same principle applies: use the strongest model for `write_extraction` and a faster/cheaper model for the other three roles.

Example:

```toml
[semantic_packages.agent_conversation_memory]
model = "claude-sonnet-4-6"

[semantic_packages.agent_conversation_memory.model_roles]
thread_aggregation = "claude-haiku-4-5"
consolidation = "claude-haiku-4-5"
query_ambiguity_resolution = "claude-haiku-4-5"
```

Equivalent env override:

```dotenv
PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__MODEL_ROLES__WRITE_EXTRACTION=claude-sonnet-4-6
```

## Embedding Providers

Embedding providers live under `embedding_providers`.

Example:

```toml
[embedding_providers.onnx]
kind = "onnx"
model = "BAAI/bge-small-en-v1.5"
```

Supported fields today:

- `kind` — `"onnx"` (Python 3.14 compatible) or `"fastembed"` (Python 3.12/3.13)
- `model` — HuggingFace model name
- `dimensions` — optional override (auto-detected from model)
- `cache_dir` — optional model cache directory (default: HuggingFace global cache)

## Vector Index

The vector index enables hybrid retrieval (lexical + vector via RRF).

Example:

```toml
[vector_index]
enabled = true
index_path = "./pallium_vector.index"
embedding_provider = "onnx"
min_similarity = 0.55
```

Supported fields today:

- `enabled` — `true` or `false` (default: `false`)
- `index_path` — file path for the usearch index
- `embedding_provider` — references an `[embedding_providers.<name>]` block
- `min_similarity` — minimum cosine similarity threshold (default: `0.55`)

Env overrides:

```dotenv
PALLIUM_VECTOR_INDEX_ENABLED=true
PALLIUM_VECTOR_INDEX_PATH=./pallium_vector.index
PALLIUM_VECTOR_INDEX_EMBEDDING_PROVIDER=onnx
PALLIUM_VECTOR_INDEX_MIN_SIMILARITY=0.55
```

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

## Common Recipes

### Use Anthropic Claude directly

```toml
[llm_providers.anthropic]
kind = "anthropic_claude"
base_url = "https://api.anthropic.com/v1"
api_key_env = "ANTHROPIC_API_KEY"

[semantic_packages.agent_conversation_memory]
implementation = "agent_conversation_memory"
llm_provider = "anthropic"
model = "claude-sonnet-4-6"

[semantic_packages.agent_conversation_memory.model_roles]
thread_aggregation = "claude-haiku-4-5"
consolidation = "claude-haiku-4-5"
query_ambiguity_resolution = "claude-haiku-4-5"
```

### Use Anthropic via a proxy with Bearer auth

Some proxy gateways require `Authorization: Bearer` instead of the native `x-api-key` header. Set `auth_style = "bearer"`:

```toml
[llm_providers.anthropic_proxy]
kind = "anthropic_claude"
base_url = "http://localhost:6655/anthropic/v1"
api_key_env = "PROXY_API_KEY"
auth_style = "bearer"

[semantic_packages.agent_conversation_memory]
implementation = "agent_conversation_memory"
llm_provider = "anthropic_proxy"
model = "claude-sonnet-4-6"
```

### Use OpenAI

```toml
[llm_providers.openai]
kind = "openai_compatible"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"

[semantic_packages.agent_conversation_memory]
implementation = "agent_conversation_memory"
llm_provider = "openai"
model = "gpt-5-mini"
```

## Read Next

- quick local setup: [getting-started.md](getting-started.md)
- integration flow: [agent-integration.md](agent-integration.md)
- API contract: [http-api.md](http-api.md)
- architecture truth: [context/architecture.md](context/architecture.md)
