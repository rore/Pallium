# spring-archunit — profile

Default zones, boundary rules, and ecosystem-specific options. Package names are placeholders — bootstrap derives the actual ones from the repo. When zones overlap (e.g., a path matches both red and blue), red wins.

## Framing — what red means here

Red means **changes that need different review behavior**, not "important code." A domain entity is important; adding a field to it is routine. A migration is important; adding an index *might* be routine, dropping a column is not. The defaults below try to keep red small enough that it fires on a minority of feature PRs. Bootstrap Phase 3 challenges every red entry with the test "would this fire on a typical PR?" — if yes, it's mis-classified and should move to `watch` or `blue`.

Most domain code, application code, and adapter code is on the **`watch`** list by default — the reporter surfaces it in the PR comment without making it a checkpoint. That's the right home for "we want a second look at this" without the alert-fatigue cost of red. (`watch` is an additive tag, not a zone — see SPEC §4.4 for the gray-vs-watch distinction.)

## Default zones

### Red — genuinely structural surface

```yaml
zones:
  red:
    # Repository contracts — signature changes ripple to every caller
    - path: src/main/java/**/domain/repository/*.java
      reason: domain repository interfaces; signature changes affect call sites
      checkpoint: architecture-review

    # Outbound port contracts (gateways to external systems)
    - path: src/main/java/**/domain/gateway/*.java
      reason: outbound gateway contracts; signature changes affect external integrations
      checkpoint: architecture-review

    # Application port interfaces (when ports live there)
    - path: src/main/java/**/application/**/port/**
      reason: architectural boundary contracts (port interfaces)
      checkpoint: architecture-review

    - path: src/main/java/**/port/**
      reason: architectural boundary contracts (when ports live at top level)
      checkpoint: architecture-review

    # Persistence contract
    - path: src/main/resources/db/migration/**
      reason: persistence contract
      checkpoint: persistence-review

    # Security
    - path: src/main/java/**/security/**
      reason: auth/security-sensitive code
      checkpoint: security-review
    - path: src/main/java/**/auth/**
      reason: auth/security-sensitive code
      checkpoint: security-review
    - path: src/main/java/**/jwt/**
      reason: token handling
      checkpoint: security-review

    # Self-protection — the rules that enforce the rules
    - path: src/test/java/**/architecture/**
      reason: dependency-rule definitions; weakening these requires explicit checkpoint
      checkpoint: architecture-review
    - path: src/test/java/**/*ArchitectureTest.java
      reason: dependency-rule definitions when not under architecture/
      checkpoint: architecture-review
    - path: agent-policy.yaml
      reason: governance source of truth; changes alter what counts as red elsewhere
      checkpoint: architecture-review

    # Infra-as-code
    - path: terraform/**
      reason: infrastructure
      checkpoint: ops-review

    # Production runtime config — only the prod profiles. The default
    # `application.yml` is on the watch list, not red, because it's edited often
    # for routine changes and the calibration data showed it never produced
    # ops-shaped review on past PRs (see docs/DECISIONS.md "Default red zones
    # were calibrated against real PR history").
    - path: src/main/resources/application-prod*.yml
      reason: production runtime configuration
      checkpoint: ops-review
```

**Note on the public API surface.** `**/*Controller.java` is *not* in the red defaults. Path-touch on a controller is a poor proxy for "API contract changed" — it fires on bug-fixes, refactors, and parameter validation just as readily as on real contract changes. The api-review checkpoint is triggered by the `api: openapi-from-controllers` semantic-diff signal instead, which detects added / removed / modified paths and operations. Controllers are on the watch list so the reporter still surfaces controller changes in the PR comment, but only real contract changes block on api-review. See `docs/DECISIONS.md` "Default red zones were calibrated against real PR history" for the firing-rate evidence behind this.

**What's deliberately NOT red here** (compared to a maximalist default):

- `domain/entity/**` — adding fields is routine; not architectural
- `domain/model/**` — value objects; same
- `domain/service/**` — orchestrators; not invariant-bearing in most Spring layouts
- `application/**` (except ports) — most application code is glue
- `infrastructure/**` / `adapter/**` — implementation; the boundary rules already protect what matters
- `**/*Controller.java` — controller-touch is a poor proxy for API change; the OpenAPI structural diff is the precise signal (see api: section)
- Non-prod `application*.yml` profiles, including the default `application.yml`

If your repo treats some of these as genuinely structural (e.g., you have a `domain/policy/` directory carrying invariants), promote them in Phase 3. The bias is toward narrower defaults; widen on evidence, not on intuition.

### Blue — agents may work autonomously

```yaml
zones:
  blue:
    - path: src/test/**
      reason: tests and verification (excluding architecture/**)

    - path: docs/**
      reason: documentation

    - path: scripts/**
      reason: local tooling

    - path: tools/**
      reason: local tooling

    - path: <api-test-collections>/**
      reason: API test collections (e.g., Bruno, Postman, Insomnia, REST Client)

    - path: src/main/java/**/adapter/**/mapper/**
      reason: isolated adapter mapping

    - path: src/main/java/**/adapter/**/persistence/**/dto/**
      reason: DB row / persistence-internal DTOs (not API surface)
```

Adapter DTOs in general (other than persistence-internal ones) are on the watch list, not blue. Promote a specific subpath to blue only when the developer confirms it's internal-only.

### Watch — surfaced in the PR comment, not a checkpoint

The `watch` list is the default home for "an agent could plausibly do this autonomously, and most of the time the result is fine, but a reviewer should at least see that it happened." No checkpoint, no merge gate — just visibility. Watch is an additive tag (not a zone), so a path on the watch list still has whatever zone classification its other matches give it; the watch entry only adds the visibility flag.

```yaml
zones:
  watch:
    # Domain code that's important but not architectural
    - path: src/main/java/**/domain/entity/**
      reason: entities; adding fields affects persistence + DTOs
    - path: src/main/java/**/domain/model/**
      reason: domain value objects
    - path: src/main/java/**/domain/service/**
      reason: domain services orchestrate flows

    # Application layer
    - path: src/main/java/**/application/**/*Service.java
      reason: application services orchestrate flows
    - path: src/main/java/**/application/**/*UseCase.java
      reason: application use cases orchestrate flows
    - path: src/main/java/**/application/**/*Handler.java
      reason: command/query handlers

    # Public API surface — controller-touch is visible but not a checkpoint;
    # api-review fires from the OpenAPI structural diff (see api: section below).
    - path: src/main/java/**/*Controller.java
      reason: controller change; structural API impact surfaced via OpenAPI diff

    # Default-profile runtime config — visible, not a checkpoint. Production
    # profiles (application-prod*.yml) stay red.
    - path: src/main/resources/application.yml
      reason: runtime configuration (default profile); visible, not a checkpoint

    # Adapter surface that may carry contract semantics
    - path: src/main/java/**/adapter/**/dto/**
      reason: adapter DTOs may be vendor contract surface
    - path: src/main/java/**/*Dto.java
      reason: shared DTOs may appear in API responses
    - path: src/main/java/**/*Configuration.java
      reason: Spring configuration affects bean wiring globally
    - path: src/main/java/**/*Filter.java
      reason: Spring filters affect request lifecycle
    - path: src/main/java/**/*Interceptor.java
      reason: Spring interceptors affect request lifecycle
```

## Default boundary rules

```yaml
boundaries:
  - id: domain-must-not-import-adapters
    description: Domain layer must not depend on adapter implementations
    from: src/main/java/**/domain/**
    forbidImports:
      - src/main/java/**/adapter/**
    severity: error

  - id: application-must-not-import-concrete-infra
    description: Application layer talks to ports, not concrete adapters
    from: src/main/java/**/application/**
    forbidImports:
      - src/main/java/**/adapter/**/persistence/**
      - src/main/java/**/adapter/**/client/**
    severity: error

  - id: controllers-must-not-access-repositories
    description: Controllers go through application services, not directly to data
    from: src/main/java/**/controller/**
    forbidImports:
      - src/main/java/**/repository/**
      - src/main/java/**/adapter/**/persistence/**
    severity: error
```

Add more rules during bootstrap based on what the repo has (e.g., "core must not import customer customization", "domain must not import vendor adapter types"; see ecosystem options below).

## API contract handling

Pick one based on what the repo has:

**SpringDoc with a generation plugin** (best signal): `org.springdoc.openapi-gradle-plugin` or equivalent installed. The CI workflow generates the spec at base and head SHAs and the reporter computes a structural diff (paths added/removed, methods added/removed/modified).

```yaml
api:
  type: openapi-from-controllers
  generationCommand: ./gradlew generateOpenApiDocs
  diffMode: structural
  checkpoint: api-review
```

See `scaffold.md` §6 for the CI worktree pattern. The local pre-push check does NOT run the generation (two builds is too slow); it relies on red-zone path classification — touched controllers fire api-review.

**Committed OpenAPI spec:**

```yaml
api:
  type: openapi-spec-file
  specPath: openapi/api.yaml
  diffMode: structural
  checkpoint: api-review
```

The reporter detects api changes by matching the diff against `specPath`.

**No public API surface:**

```yaml
api:
  type: none
```

Controllers are red-zone files via path classification regardless of `api.type`, so an api-review checkpoint still fires when controllers change. The diff modes above add structural detail to the verdict; without them, you still know "the surface was touched."

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
```

## Build / test commands

| Action | Command |
|---|---|
| Run all tests | `./gradlew test` |
| Run only architecture tests | `./gradlew test --tests '*ArchitectureTest'` |
| Run local agent-redline check | `./scripts/agent-redline-check.sh` |
| Generate OpenAPI (if plugin present) | `./gradlew generateOpenApi` |

## Default PR-size thresholds

Use these unless the developer asks for tighter or looser bounds in Phase 3. They're the same numbers the reference Spring services run with, calibrated to fire on roughly the top decile of feature PRs.

```yaml
prRules:
  maxChangedFiles: { warn: 50, fail: 100 }
  maxLinesChanged: { warn: 1000, fail: 2000 }
```

Tighter bounds (e.g., `warn: 15 / fail: 40` for files) make sense for fixture-sized services or libraries with very small change scope. Looser bounds rarely; PRs over 2000 lines are almost always wrong-sized regardless of repo.

## Ecosystem-specific behavior

- **`@RestController` on internal-only endpoints.** Ask the developer which controllers are internal-only and exclude them from `api-review` triggering (`excludes:` in the policy).
- **Generated source directories.** If the build generates DTOs (OpenAPI codegen, JOOQ, MapStruct, etc.), add the generated directory to `excludes:` so it's not classified at all.
- **ArchUnit `DoNotIncludeTests` option.** When generating the architecture test class, verify this option is set so test classes aren't analyzed for boundary violations.
- **`application.yml` env-var overrides.** Runtime config zone covers the YAML; environment variable overrides operate at deploy time and are out of scope for the policy.
