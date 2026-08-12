# jvm-archunit — operating-mode notes

JVM-specific behavior in addition to the core operating-mode rules.

## Generated sources

If the build generates Java sources (OpenAPI codegen, JOOQ, MapStruct, Immutables, gRPC stubs), generated directories should be in `excludes:` of the policy. If you find generated sources that aren't excluded, surface in the PR description and suggest a policy update.

## Multi-tenant persistence

If `persistence.notes` mentions multi-tenant migrations, the `persistence-review` checkpoint requires a rollout plan, not just a schema diff. Ask the developer about per-tenant impact when proposing a migration.

## ArchUnit `DoNotIncludeTests`

When generating the architecture test class, set `ImportOption.DoNotIncludeTests.class` (the `scaffold.md` §2 template already does this). Without it, test classes get analyzed and architecture rules fire on test-only code.

## Kotlin

ArchUnit reads bytecode, so Java rules apply to Kotlin. Kotlin-specific notes:

- Top-level functions compile to a synthetic `<FileName>Kt` class. Package-based rules (`resideInAPackage`) are unaffected; name-based rules (`haveSimpleName`, etc.) must target the `Kt` class to match top-level functions.
- `internal` modifier in Kotlin compiles to `public final` bytecode with name mangling. ArchUnit cannot enforce Kotlin's `internal` visibility from bytecode alone — use the `internal` package convention for boundary rules instead.

## Spring addendum

The sections below apply only when `spring-boot-starter-*` appears in `build.gradle` / `pom.xml`.

### Treat as red even if the policy doesn't say so

- **`@Configuration` classes.** Changes to bean wiring, scope, or initialization order are globally consequential.
- **`@RestController` annotation add/remove.** Even on internal endpoints — confirm whether the endpoint is genuinely internal-only or part of a contract.
- **`@Transactional` boundary changes.** Add/remove/propagation changes have runtime consequences tests often miss.
- **Spring Security configuration changes.** Treat as `security-review` even if the file is outside `**/security/**`.

### `application.yml` changes

Spring Boot environment variables (`SPRING_FOO_BAR_BAZ`) override YAML at deploy time. If a YAML edit changes a default that has a corresponding env var in production, treat as `ops-review` even if the YAML edit looks small.
