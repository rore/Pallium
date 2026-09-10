# jvm-archunit — profile

Default zones, boundary rules, and ecosystem options. Package names are placeholders; bootstrap derives actual ones. When zones overlap, red wins.

This profile enumerates **three shapes**: layered service (with a Spring addendum), library/SDK, and zone-only fallback. Bootstrap inspects, picks one (or proposes two when ambiguous), developer confirms.

Globs use `**/...` form so they match both standard `src/main/java/**` and Maven-multimodule `*/src/main/java/**` without duplication.

## Shape detection (Phase 1)

| Signal | Implies shape |
|---|---|
| `spring-boot-starter-*` or `org.springframework.boot:*` in `build.gradle` / `pom.xml` | layered service + Spring addendum |
| Web framework dep (`jakarta.ws.rs:*`, `io.javalin:javalin`, `io.ktor:*`, `io.helidon:*`, `io.dropwizard:*`, `org.eclipse.jetty:*`); or layer dirs `controller/`, `domain/`, `application/`, `adapter/`, `infrastructure/`, `core/`, `port/` | layered service |
| Build artifact is `jar` for distribution (`maven-publish`, `nexus-publish`, `org.gradle.api.publish`); `module-info.java` present; no web framework dep | library / SDK |
| `com.android.application` / `com.android.library` plugin, OR Spark / Beam / Flink deps, OR Hadoop deps | zone-only fallback |
| None match | zone-only fallback (developer can adjust) |

**Layout variants** (same shape — bootstrap derives, not separate shapes):
- standard: `src/main/java/<base-package>/...`, `src/main/kotlin/<base-package>/...`
- multi-module: each Gradle/Maven submodule has its own `src/main/...`
- mixed Java/Kotlin: both source roots; ArchUnit analyzes both because it operates on bytecode

## Shape: layered service

Red means **changes that need different review behavior**, not "important code". A red zone that fires on every feature PR is alert fatigue.

### Default zones

#### Red — genuinely structural surface

```yaml
zones:
  red:
    # Repository contracts — signature changes ripple to every caller
    - path: "src/main/java/**/domain/repository/*.java"
      reason: domain repository interfaces; signature changes affect call sites
      checkpoint: architecture-review

    # Outbound port contracts (gateways to external systems)
    - path: "src/main/java/**/domain/gateway/*.java"
      reason: outbound gateway contracts; signature changes affect external integrations
      checkpoint: architecture-review

    # Application port interfaces (when ports live there)
    - path: "src/main/java/**/application/**/port/**"
      reason: architectural boundary contracts (port interfaces)
      checkpoint: architecture-review

    - path: "src/main/java/**/port/**"
      reason: architectural boundary contracts (when ports live at top level)
      checkpoint: architecture-review

    # Persistence contract
    - path: "src/main/resources/db/migration/**"
      reason: persistence contract
      checkpoint: persistence-review

    # Security
    - path: "src/main/java/**/security/**"
      reason: auth/security-sensitive code
      checkpoint: security-review
    - path: "src/main/java/**/auth/**"
      reason: auth/security-sensitive code
      checkpoint: security-review
    - path: "src/main/java/**/jwt/**"
      reason: token handling
      checkpoint: security-review

    # Self-protection — the rules that enforce the rules
    - path: "src/test/java/**/architecture/**"
      reason: dependency-rule definitions; weakening these requires explicit checkpoint
      checkpoint: architecture-review
    - path: "src/test/java/**/*ArchitectureTest.java"
      reason: dependency-rule definitions when not under architecture/
      checkpoint: architecture-review
    - path: "agent-redline-policy.yaml"
      reason: governance source of truth; changes alter what counts as red elsewhere
      checkpoint: architecture-review

    # Infra-as-code
    - path: "terraform/**"
      reason: infrastructure
      checkpoint: ops-review
```

**What's deliberately NOT red** (compared to a maximalist default):

- `domain/entity/**` — adding fields is routine; not architectural
- `domain/model/**` — value objects; same
- `domain/service/**` — orchestrators; not invariant-bearing in most layouts
- `application/**` (except ports) — most application code is glue
- `infrastructure/**` / `adapter/**` — implementation; the boundary rules already protect what matters

If your repo treats some of these as genuinely structural (e.g., you have a `domain/policy/` directory carrying invariants), promote them in Phase 3. The bias is toward narrower defaults; widen on evidence, not on intuition.

#### Blue — agents may work autonomously

```yaml
zones:
  blue:
    - path: "src/test/**"
      reason: tests and verification (excluding architecture/**)

    - path: "docs/**"
      reason: documentation

    - path: "scripts/**"
      reason: local tooling

    - path: "tools/**"
      reason: local tooling

    - path: "<api-test-collections>/**"
      reason: API test collections (e.g., Bruno, Postman, Insomnia, REST Client)

    - path: "src/main/java/**/adapter/**/mapper/**"
      reason: isolated adapter mapping

    - path: "src/main/java/**/adapter/**/persistence/**/dto/**"
      reason: DB row / persistence-internal DTOs (not API surface)
```

Adapter DTOs in general (other than persistence-internal ones) are on the watch list, not blue. Promote a specific subpath to blue only when the developer confirms it's internal-only.

#### Watch — surfaced in the PR comment, not a checkpoint

```yaml
zones:
  watch:
    # Domain code that's important but not architectural
    - path: "src/main/java/**/domain/entity/**"
      reason: entities; adding fields affects persistence + DTOs
    - path: "src/main/java/**/domain/model/**"
      reason: domain value objects
    - path: "src/main/java/**/domain/service/**"
      reason: domain services orchestrate flows

    # Application layer
    - path: "src/main/java/**/application/**/*Service.java"
      reason: application services orchestrate flows
    - path: "src/main/java/**/application/**/*UseCase.java"
      reason: application use cases orchestrate flows
    - path: "src/main/java/**/application/**/*Handler.java"
      reason: command/query handlers

    # Adapter surface that may carry contract semantics
    - path: "src/main/java/**/adapter/**/dto/**"
      reason: adapter DTOs may be vendor contract surface
    - path: "src/main/java/**/*Dto.java"
      reason: shared DTOs may appear in API responses
```

### Default boundary rules

```yaml
boundaries:
  - id: domain-must-not-import-adapters
    description: Domain layer must not depend on adapter implementations
    from: "src/main/java/**/domain/**"
    forbidImports:
      - "src/main/java/**/adapter/**"
    severity: error

  - id: application-must-not-import-concrete-infra
    description: Application layer talks to ports, not concrete adapters
    from: "src/main/java/**/application/**"
    forbidImports:
      - "src/main/java/**/adapter/**/persistence/**"
      - "src/main/java/**/adapter/**/client/**"
    severity: error

  - id: controllers-must-not-access-repositories
    description: Controllers go through application services, not directly to data
    from: "src/main/java/**/controller/**"
    forbidImports:
      - "src/main/java/**/repository/**"
      - "src/main/java/**/adapter/**/persistence/**"
    severity: error

boundaryAdapter:
  outputFormat: junit-xml
  outputPath: build/test-results/test/TEST-*ArchitectureTest.xml
```

Add more rules during bootstrap based on what the repo has (e.g., "core must not import customer customization", "domain must not import vendor adapter types"; see ecosystem options below).

### Default API contract handling

For Spring services using SpringDoc, see the Spring addendum below.

**Committed OpenAPI spec:**

```yaml
api:
  type: openapi-spec-file
  specPath: openapi/api.yaml
  diffMode: structural
  checkpoint: api-review
```

**No public API surface:**

```yaml
api:
  type: none
```

### Default PR-size thresholds

```yaml
prRules:
  maxChangedFiles: { warn: 50, fail: 100 }
  maxLinesChanged: { warn: 1000, fail: 2000 }
```

## Spring addendum

If `spring-boot-starter-*` is in `build.gradle` / `pom.xml`, augment (don't replace) the layered-service zones:

```yaml
zones:
  # Additional red:
  red:
    - path: "src/main/resources/application-prod*.yml"
      reason: production runtime configuration
      checkpoint: ops-review
  # Additional watch:
  watch:
    - path: "src/main/java/**/*Controller.java"
      reason: controller change; structural API impact surfaced via OpenAPI diff
    - path: "src/main/resources/application.yml"
      reason: runtime configuration (default profile); visible, not a checkpoint
    - path: "src/main/java/**/*Configuration.java"
      reason: Spring configuration affects bean wiring globally
    - path: "src/main/java/**/*Filter.java"
      reason: Spring filters affect request lifecycle
    - path: "src/main/java/**/*Interceptor.java"
      reason: Spring interceptors affect request lifecycle
```

### API contract handling — SpringDoc

**SpringDoc with a generation plugin** (best signal): `org.springdoc.openapi-gradle-plugin` or equivalent installed. The CI workflow generates the spec at base and head SHAs and the reporter computes a structural diff (paths added/removed, methods added/removed/modified).

```yaml
api:
  type: openapi-from-controllers
  generationCommand: ./gradlew generateOpenApiDocs
  diffMode: structural
  checkpoint: api-review
```

See `scaffold.md` §6 for the CI worktree pattern. The local pre-push check does NOT run the generation (two builds is too slow); it relies on red-zone path classification — touched controllers fire api-review.

- **`@RestController` on internal-only endpoints.** Ask the developer which controllers are internal-only and exclude them from `api-review` triggering (`excludes:` in the policy).
- **`application.yml` env-var overrides.** Runtime config zone covers the YAML; environment variable overrides operate at deploy time and are out of scope for the policy.

**Note on the public API surface.** `**/*Controller.java` is *not* in the red defaults. Path-touch on a controller is a poor proxy for "API contract changed" — it fires on bug-fixes, refactors, and parameter validation just as readily as on real contract changes. The api-review checkpoint is triggered by the `api: openapi-from-controllers` semantic-diff signal above, which detects added / removed / modified paths and operations. Controllers are on the watch list so the reporter still surfaces controller changes in the PR comment, but only real contract changes block on api-review.

## Shape: library / SDK

For Maven Central / nexus-publish artifacts whose value is their public API.

### Default zones

```yaml
zones:
  red:
    # Public API surface — package-info, module-info, exported packages
    - path: "**/src/main/java/**/package-info.java"
      reason: published package-level documentation and exports
      checkpoint: api-review
    - path: "**/src/main/java/module-info.java"
      reason: JPMS module declaration; exports and requires shape the public API
      checkpoint: api-review
    - path: "**/src/main/kotlin/**/*.kt"
      reason: Kotlin public-API source — every public symbol is part of the contract
      checkpoint: api-review

    # Self-protection
    - path: "**/build.gradle"
      reason: build / dependency-rule configuration
      checkpoint: architecture-review
    - path: "**/build.gradle.kts"
      reason: build / dependency-rule configuration
      checkpoint: architecture-review
    - path: "pom.xml"
      reason: build / dependency-rule configuration
      checkpoint: architecture-review
    - path: "agent-redline-policy.yaml"
      reason: governance source of truth
      checkpoint: architecture-review
    - path: "src/test/java/**/architecture/**"
      reason: dependency-rule definitions
      checkpoint: architecture-review
    - path: "src/test/java/**/*ArchitectureTest.java"
      reason: dependency-rule definitions when not under architecture/
      checkpoint: architecture-review

  watch:
    - path: "**/src/main/java/**/internal/**"
      reason: internal packages — public by Java visibility but not part of the contract
    - path: "**/CHANGELOG.md"
      reason: published changelog
    - path: "**/README.md"
      reason: README is part of the published artifact

  blue:
    - path: "**/src/test/**"
      reason: tests
    - path: "docs/**"
      reason: documentation
    - path: "scripts/**"
      reason: local tooling
```

The Kotlin red-zone glob is broad on purpose — Kotlin source has no `package-info.java` equivalent, and the tooling to reliably detect "added a public symbol" from a textual diff is absent. The first 2–4 weeks of shadow mode is where the team narrows it (e.g., to `**/api/**` if internal packages are conventionally separated).

### Default boundary rules

Only generate if the repo actually has `internal/` subpackages — don't fabricate.

```yaml
boundaries:
  - id: public-must-not-import-internal
    description: Public API packages must not depend on internal implementation details
    from: "src/main/java/**"
    forbidImports:
      - "src/main/java/**/internal/**"
    severity: error

boundaryAdapter:
  outputFormat: junit-xml
  outputPath: build/test-results/test/TEST-*ArchitectureTest.xml
```

### Default PR-size thresholds

```yaml
prRules:
  maxChangedFiles: { warn: 20, fail: 50 }
  maxLinesChanged: { warn: 500, fail: 1000 }
```

### API contract handling

Libraries don't have an HTTP/RPC surface; the public API is the published artifact's exported packages and types. Two options:

```yaml
# Default — omit the api: block entirely. Equivalent to:
api:
  type: none
```

Detection of API breakage in libraries belongs to a binary-diff tool — `japicmp`, `revapi`, or the language ecosystem's equivalent — run as a Gradle/Maven task. agent-redline doesn't replicate that tool; it triggers the `api-review` checkpoint via the red-zone path classification (`module-info.java`, `package-info.java`, public-API package source). The binary-diff tool runs in CI alongside agent-redline; the two are independent signals on the same PR.

If a binary-diff task is already configured (e.g., `me.champeau.gradle.japicmp`), document it in the consuming repo's `AGENTS.md` so reviewers see both signals together. Don't try to embed binary-diff invocation in the agent-redline workflow.

## Shape: zone-only fallback

For Android apps, batch / streaming pipelines (Spark, Beam, Flink), Hadoop, mixed monorepos. ArchUnit either doesn't fit the build (Android variants) or doesn't carry useful structural rules (data pipelines).

```yaml
zones:
  red:
    - path: "**/src/main/resources/db/migration/**"
      reason: persistence contract
      checkpoint: persistence-review
    - path: "**/changelog*.xml"
      reason: persistence contract (Liquibase)
      checkpoint: persistence-review
    - path: "**/src/main/java/**/security/**"
      reason: auth/security-sensitive code
      checkpoint: security-review
    - path: "agent-redline-policy.yaml"
      reason: governance source of truth
      checkpoint: architecture-review
    - path: "terraform/**"
      reason: infrastructure
      checkpoint: ops-review

  watch:
    - path: "**/src/main/**"
      reason: production code (no boundary backend; surface visibility only)
    - path: "**/build.gradle*"
      reason: build configuration
    - path: "pom.xml"
      reason: build configuration

  blue:
    - path: "**/src/test/**"
      reason: tests
    - path: "docs/**"
      reason: documentation

boundaryAdapter:
  outputFormat: none

prRules:
  maxChangedFiles: { warn: 30, fail: 80 }
  maxLinesChanged: { warn: 800, fail: 1500 }
```

Reporter skips boundary parsing. Zones, persistence/security signals, PR-size still run.

## Ecosystem options

Ask the developer about these in Phase 3 and include if relevant.

### Multi-tenant persistence

```yaml
persistence:
  migrationPaths:
    - src/main/resources/db/migration/**
    - src/main/resources/db/tenant-migration/**
  checkpoint: persistence-review
  notes: |
    Multi-tenant migrations apply per-tenant. Persistence-review checkpoint
    must include a rollout plan, not just a schema diff.
```

### Third-party adapter contracts

```yaml
zones:
  red:
    - path: src/main/java/**/adapter/<vendor>/**/dto/**
      reason: third-party API contract surface
      checkpoint: api-review
    - path: src/main/java/**/adapter/<vendor>/**/request/**
      reason: third-party API contract surface
      checkpoint: api-review
    - path: src/main/java/**/adapter/<vendor>/**/response/**
      reason: third-party API contract surface
      checkpoint: api-review

boundaries:
  - id: domain-must-not-import-vendor-types
    description: Domain stays free of vendor-specific adapter types
    from: src/main/java/**/domain/**
    forbidImports:
      - src/main/java/**/adapter/<vendor>/**

boundaryAdapter:
  outputFormat: junit-xml
  outputPath: build/test-results/test/TEST-*ArchitectureTest.xml
```

### Customer-specific code that must not leak into core

```yaml
zones:
  red:
    - path: src/main/java/**/core/**
      reason: shared core; customer-specific code must not leak in
      checkpoint: architecture-review

boundaries:
  - id: core-must-not-import-customer-customization
    description: Shared core stays clean of customer-specific code
    from: src/main/java/**/core/**
    forbidImports:
      - src/main/java/**/customer/**
    severity: error

boundaryAdapter:
  outputFormat: junit-xml
  outputPath: build/test-results/test/TEST-*ArchitectureTest.xml
```

## Build / test commands

| Action | Command |
|---|---|
| Run all tests | `./gradlew test` |
| Run only architecture tests | `./gradlew test --tests '*ArchitectureTest'` |
| Run local agent-redline check | `./scripts/agent-redline-check.sh` |
| Generate OpenAPI (SpringDoc plugin) | `./gradlew generateOpenApiDocs` |

## JVM-specific behavior

- **Generated source directories.** If the build generates DTOs (OpenAPI codegen, JOOQ, MapStruct, etc.), add the generated directory to `excludes:` so it's not classified at all.
- **ArchUnit `DoNotIncludeTests` option.** When generating the architecture test class, verify this option is set so test classes aren't analyzed for boundary violations.
