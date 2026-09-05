# Configuration

This page explains Pallium's local configuration surface today.

## Capability setup

Pallium has configuration for the local service and storage, Relay, Session
History retrieval, optional embedding search, and optional derived-memory
packages.

The intended base setup is a local service with Relay and lexical Session
History, with no LLM required. That package-independent runtime is queued work,
not current behavior. Until it ships, the normal installation still needs a
configured semantic package, model, and provider key. The examples below reflect
that transitional implementation.

Do not remove current provider configuration on the assumption that the future
base setup is already available.

**Contents:**
[Quick Reference](#quick-reference) ·
[Configuration Sources](#configuration-sources) ·
[Minimal Setups](#minimal-local-setups) ·
[TOML Structure](#toml-structure) ·
[Storage](#storage) ·
[Observability](#observability) ·
[Retention](#retention) ·
[Provider Blocks](#provider-blocks) ·
[Semantic Packages](#semantic-packages) ·
[Prompt Variants](#prompt-variants) ·
[Model Roles](#model-roles) ·
[Embedding Providers](#embedding-providers) ·
[Vector Index](#vector-index) ·
[Current Defaults](#current-defaults) ·
[Common Recipes](#common-recipes) ·
[Troubleshooting](#troubleshooting)

## Quick Reference

| What | Where | Key fields |
|------|-------|------------|
| LLM provider | `[llm_providers.<name>]` in TOML | `kind`, `base_url`, `api_key_env`, `api_key_file` |
| Semantic package | `[semantic_packages.<name>]` in TOML | `llm_provider`, `model` |
| Model roles | `[semantic_packages.<name>.model_roles]` | `write_extraction`, `thread_aggregation`, `consolidation`, `query_ambiguity_resolution` |
| Secrets | `.env.local`, alternate env file, or provider key file | `ANTHROPIC_API_KEY`, `PALLIUM_OPENAI_API_KEY`, `api_key_file` |
| Storage | `[storage]` in TOML | `backend`, `sqlite_url` |
| Embedding | `[embedding_providers.<name>]` in TOML | `kind`, `model`, `query_prefix`, `passage_prefix` |
| Vector index | `[vector_index]` in TOML | `enabled`, `min_similarity` |
| Debug logs | `[observability]` in TOML | `integration_debug = true` |

Minimum to activate the live LLM path: set `llm_provider` and `model` on a
semantic package, and provide the API key in `.env.local`.

---

Use this page when you need to:

- wire a live LLM provider
- override prompt variants or model roles
- tune vector retrieval or embedding settings
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

[llm_providers.anthropic]
kind = "anthropic_claude"
base_url = "https://api.anthropic.com/v1"
api_key_env = "ANTHROPIC_API_KEY"

[semantic_packages.agent_conversation_memory]
llm_provider = "anthropic"
model = "claude-sonnet-4-6"
```

And in `.env.local`:

```dotenv
ANTHROPIC_API_KEY=your-key
```

That is enough to run the full semantic path. Prompt variants, model roles,
embedding, and vector retrieval all have working defaults — hybrid retrieval
is enabled out of the box with a local ONNX embedding provider.

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
- `api_key_file` - read the bearer/native auth token from a local secret file
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
PALLIUM_PROVIDER__OPENAI__API_KEY_FILE=/absolute/path/to/api-key-file
```

## Semantic Packages

Semantic packages live under `semantic_packages`.

Example:

```toml
[semantic_packages.agent_conversation_memory]
implementation = "agent_conversation_memory"
llm_provider = "openai"
model = "gpt-5-mini"
prompt_variant = "strict_typed_memory_v8b_work_refs_separate"
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
PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__PROMPT_VARIANT=strict_typed_memory_v8b_work_refs_separate
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
prompt_variant = "strict_typed_memory_v8b_work_refs_separate"

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
- `fact_extraction` — conversational_knowledge per-thread fact extraction (handles 10-20 structured facts)
- `fact_consolidation` — conversational_knowledge cross-thread consolidation with contradiction detection (needs strong reasoning)

Benchmarked recommendation (Anthropic Claude):

**agent_conversation_memory roles:**

| Role | Model class | Rationale |
|---|---|---|
| `write_extraction` | Sonnet (default) | 14-field schema with strict evidence rules. Quality-sensitive — needs the strongest model. |
| `thread_aggregation` | Haiku | Simpler schema, code has fallback defaults. Benchmarked: 11/11 routing, 100% work resumption contract. |
| `consolidation` | Haiku | Simplest schemas. Same benchmark results as thread_aggregation. |
| `query_ambiguity_resolution` | Haiku | Hot path (800ms timeout), simple A/B decision. Speed matters more than depth. |

**conversational_knowledge roles:**

| Role | Model class | Rationale |
|---|---|---|
| `fact_extraction` | Haiku (default) | Produces up to 20 structured facts per chunk. Haiku handles this reliably. |
| `fact_consolidation` | Sonnet (auto-default) | Contradiction detection requires discriminating single-valued property conflicts from multi-valued predicates and separate events. Sonnet: P=0.94 R=1.00 vs Haiku: P=0.82 R=0.82. |

The `fact_consolidation` role auto-upgrades from Haiku to Sonnet when the package model is Haiku and no explicit override is configured.

When using OpenAI or other providers, the same principle applies: use the strongest model for `write_extraction` and `fact_consolidation`, and a faster/cheaper model for the other roles.

Example:

```toml
[semantic_packages.agent_conversation_memory]
model = "claude-sonnet-4-6"

[semantic_packages.agent_conversation_memory.model_roles]
thread_aggregation = "claude-haiku-4-5"
consolidation = "claude-haiku-4-5"
query_ambiguity_resolution = "claude-haiku-4-5"
```

For conversational_knowledge, `fact_consolidation` defaults to Sonnet automatically.
To override explicitly:

```toml
[semantic_packages.conversational_knowledge]
model = "claude-haiku-4-5"

# Optional — fact_consolidation auto-upgrades to Sonnet when omitted
[semantic_packages.conversational_knowledge.model_roles]
fact_consolidation = "claude-sonnet-4-6"
fact_extraction = "claude-haiku-4-5"
```

Equivalent env override:

```dotenv
PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__MODEL_ROLES__WRITE_EXTRACTION=claude-sonnet-4-6
```

## Embedding Providers

Embedding providers live under `embedding_providers`.

Example (multilingual, recommended):

```toml
[embedding_providers.onnx]
kind = "onnx"
model = "intfloat/multilingual-e5-small"
```

Example (English-only):

```toml
[embedding_providers.onnx]
kind = "onnx"
model = "BAAI/bge-small-en-v1.5"
```

Supported fields today:

- `kind` — `"onnx"` or `"fastembed"` (fastembed requires Python 3.12/3.13; onnx works on all supported versions)
- `model` — HuggingFace model name
- `dimensions` — optional override (auto-detected from model)
- `cache_dir` — optional model cache directory (default: HuggingFace global cache)
- `query_prefix` — optional prefix added to query text before embedding
- `passage_prefix` — optional prefix added to passage text before embedding

Some embedding models (notably the E5 family) require query/passage prefixes
for best results. Pallium auto-detects the correct prefixes for known model
families — you only need to set `query_prefix` and `passage_prefix` manually
if you use a model that Pallium doesn't recognize or if you want to override
the defaults.

## Vector Index

The vector index enables hybrid retrieval (lexical + vector via RRF).

Vector retrieval is **enabled by default** with a default ONNX embedding
provider. It requires the `vector` optional extra:

```bash
pip install -e ".[vector]"
```

On first run, the model weights are
downloaded automatically (~130 MB for `bge-small-en-v1.5`, ~470 MB for
`multilingual-e5-small`).

To override:

```toml
[vector_index]
index_path = "./custom_vector.index"
embedding_provider = "custom"
min_similarity = 0.4

[embedding_providers.custom]
kind = "fastembed"
model = "some-other-model"
```

To disable vector retrieval:

```toml
[vector_index]
enabled = false
```

Supported fields today:

- `enabled` — `true` or `false` (default: `true`)
- `index_path` — file path for the usearch index (default: `./vector_index`)
- `embedding_provider` — references an `[embedding_providers.<name>]` block (default: `"onnx"`)
- `min_similarity` — minimum cosine similarity threshold (default: `0.55`)

Env overrides:

```dotenv
PALLIUM_VECTOR_INDEX_ENABLED=true
PALLIUM_VECTOR_INDEX_PATH=./vector_index
PALLIUM_VECTOR_INDEX_EMBEDDING_PROVIDER=onnx
PALLIUM_VECTOR_INDEX_MIN_SIMILARITY=0.55
```

## Features

Progressively-rolling-out capabilities gated by explicit flags. Every
flag has a safe-off default. Enable per-installation via `pallium.local.toml`
or override via `PALLIUM_FEATURES_<FLAG_UPPER>` env variable (env wins).

```toml
[features]
operational_fact_derivation = false
typed_extraction_shadow     = false
```

- `operational_fact_derivation` — when true, the `agent_work_trace` plugin
  derives `operational_fact` memories from tool-usage traces at thread-
  rebuild time. Both this flag AND the `[semantic_packages.agent_work_trace]`
  block must be enabled. Delivery is on-demand only; retrieval requires
  either a Phase-4 trigger (`post_tool_failure`, `retry_threshold`,
  `session_start_checkpoint`, `user_explicit`) or the token-based
  `operational_intent` signal on the query. Default off.
- `typed_extraction_shadow` — when true, every source item that finishes
  the live extractor is ALSO fed through a single-call strict-JSON typed
  extractor whose output lands in `memory_objects_shadow`. Zero effect on
  live retrieval; used for offline comparison via
  `evals/typed_extraction_shadow/compare.py`. Default off (extra LLM cost).

## Injection Policy (Abstention)

Per-type control over whether proactive injection is permitted. Modes
are `proactive` (score-gated), `event` (deterministic-trigger only),
`on_demand` (explicit query only), `suspended` (hidden entirely on read
and inject). Missing types default to `proactive` — except
`operational_fact`, which the routing gate defaults to `on_demand`
regardless of config, to preserve the zero-proactive design invariant.

```toml
[injection.policy.types.investigation_outcome]
mode = "on_demand"

[injection.policy.types.thread_summary]
mode = "on_demand"

[injection.policy.types.fact_summary]
mode = "suspended"

[injection.policy.types.task_checkpoint]
mode = "event"

[injection.policy.types.operational_fact]
mode = "on_demand"

# Optional per-container override:
[[injection.policy.containers]]
container_ref = "git:example/repo"
[injection.policy.containers.types.task_checkpoint]
mode = "on_demand"
```

Full spec: [`docs/specs/2026-06-27-injection-policy-abstention.md`](specs/2026-06-27-injection-policy-abstention.md).

## Current Defaults

The following defaults apply when fields are omitted:

- `default_use_case = "demo_agent_memory"`
- `agent_conversation_memory.prompt_variant` defaults to
  `"strict_typed_memory_v8b_work_refs_separate"`
- `agent_conversation_memory.resolver_enabled` defaults to `true`
- `agent_conversation_memory.resolver_timeout_ms` defaults to `800`
- `model_roles` defaults to empty — all roles use the package `model`
  - Exception: `conversational_knowledge.fact_consolidation` auto-upgrades to Sonnet when the package model is Haiku
- `vector_index.enabled` defaults to `true`
- `vector_index.embedding_provider` defaults to `"onnx"`
- `vector_index.index_path` defaults to `"./vector_index"`
- `vector_index.min_similarity` defaults to `0.55`

You only need to set `llm_provider` and `model` on a semantic package for the
live LLM path to activate. Everything else has a working default.

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

## Provider Recipes

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
