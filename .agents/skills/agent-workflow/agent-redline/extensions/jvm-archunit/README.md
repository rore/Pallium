# jvm-archunit — agent-redline language extension

The reference language extension for **JVM repositories (Java, Kotlin)** using **ArchUnit** as the boundary-rule backend. Spring Boot, plain Java/Kotlin services, and Gradle/Maven-publishable libraries are all in scope; bootstrap detects the shape and applies the matching defaults plus any framework addendum.

## When to pick this extension

Use this extension if your repo is:

- A JVM service or library — Java 17+ or Kotlin
- Built with Gradle (Kotlin or Groovy DSL) or Maven
- Organized in a hexagonal, layered, or onion-style package layout (services), or a public-API package layout (libraries)
- (Optional) using Spring Boot — covered by the Spring addendum
- (Optional) using Flyway or Liquibase migrations
- (Optional) using Spring Security / OAuth / JWT (covered by the Spring addendum)

If the repo uses Scala, this extension does not yet apply — Scala support is roadmap. ArchUnit handles Scala bytecode, but defaults and conventions for sbt + package objects + implicits aren't proven.

The extension covers three shapes:

1. **Layered service** — services with API/domain/adapters layers. Spring Boot is the dominant case and ships an addendum that augments these defaults; non-Spring services (plain JAX-RS, custom HTTP, gRPC) use the same shape without the addendum.
2. **Library / SDK** — Maven or Gradle artifacts whose value is their public API. Different red-zone defaults (`module-info.java`, package-info, public-API packages) and tighter PR-size thresholds.
3. **Zone-only fallback** — Android, Spark / Beam / Flink batch, mixed monorepos, or anything where ArchUnit isn't a fit. `boundaryAdapter: outputFormat: none`; the reporter skips the boundary leg but zones, persistence/security signals, and PR-size still run.

`profile.md` enumerates the three shapes; bootstrap inspects the repo, picks one (or proposes two when ambiguous), and the developer confirms.

## What's inside

| File | What it is |
|---|---|
| `README.md` | This file. |
| `profile.md` | Default zones, boundary rules, and JVM-specific gotchas — broken into the three shapes plus the Spring addendum. The agent reads this during bootstrap to draft `agent-redline-policy.yaml`. |
| `scaffold.md` | How the agent generates the ArchUnit test class, the build wiring, and the CI snippet. The Spring addendum covers SpringDoc OpenAPI generation. |
| `operating.md` | Stack-specific operating-mode notes the agent reads when working in a JVM repo. The Spring addendum covers `@Configuration`, `@RestController`, `@Transactional`, Spring Security. |
| `adapter.yaml` | Tells the reporter where ArchUnit writes its output and what format it's in (JUnit XML). |

## Why ArchUnit

[ArchUnit](https://www.archunit.org/) is open source, JUnit-friendly, and built specifically for package-dependency rules. It analyzes compiled bytecode (Java + Kotlin both produce bytecode it understands), so it finds real violations rather than textual matches. It drops in as one test class and integrates with the existing `./gradlew test` task.

Alternatives (jQAssistant, Spring Modulith, Semgrep) are reasonable for some teams but bring more weight or are less natural for layered architecture rules. This extension commits to ArchUnit; teams that need a different backend can fork the extension or build their own.

## Pointers

- agent-redline core: [../../README.md](https://github.com/rore/agent-redline/blob/main/README.md)
- How to build a different extension: [../../docs/EXTENSIONS.md](https://github.com/rore/agent-redline/blob/main/docs/EXTENSIONS.md)
- Policy schema: [../../docs/POLICY_SCHEMA.md](https://github.com/rore/agent-redline/blob/main/docs/POLICY_SCHEMA.md)
