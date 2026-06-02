# spring-archunit — operating-mode notes

Spring-specific behavior in addition to the core operating-mode rules.

## Treat as red even if the policy doesn't say so

These come up in Spring services often enough that the agent should be cautious regardless of zone classification:

- **`@Configuration` classes.** Changes to bean wiring, scope, or initialization order are globally consequential.
- **`@RestController` annotation add/remove.** Even on internal endpoints — confirm whether the endpoint is genuinely internal-only or part of a contract.
- **`@Transactional` boundary changes.** Add/remove/propagation changes have runtime consequences tests often miss.
- **Spring Security configuration changes.** Treat as `security-review` even if the file is outside `**/security/**`.

## Generated sources

If the build generates Java sources (OpenAPI codegen, JOOQ, MapStruct, etc.), generated directories should be in `excludes:` of the policy. If you find generated sources that aren't excluded, surface in the PR description and suggest a policy update.

## Multi-tenant persistence

If `persistence.notes` mentions multi-tenant migrations, the `persistence-review` checkpoint requires a rollout plan, not just a schema diff. Ask the developer about per-tenant impact when proposing a migration.

## `application.yml` changes

Spring Boot environment variables (`SPRING_FOO_BAR_BAZ`) override YAML at deploy time. If a YAML edit changes a default that has a corresponding env var in production, treat as `ops-review` even if the YAML edit looks small.
