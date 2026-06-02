# spring-archunit — agent-redline language extension

The reference language extension for **Spring Boot services** using **ArchUnit** as the boundary-rule backend.

## When to pick this extension

Use this extension if your repo is:

- Spring Boot
- Java 17+ or Kotlin
- Built with Gradle (Kotlin or Groovy DSL) or Maven
- Organized in a hexagonal, layered, or onion-style package layout
- Serving REST APIs (OpenAPI from controllers, or a committed spec file)
- (Optional) using Flyway or Liquibase migrations
- (Optional) using Spring Security / OAuth / JWT

If the repo uses GraphQL, gRPC, or has no HTTP surface, the extension still works for boundary rules and zones — adapt the API section in your generated `agent-policy.yaml`.

## What's inside

| File | What it is |
|---|---|
| `README.md` | This file. |
| `profile.md` | Default zones, boundary rules, gotchas. The agent reads this during bootstrap to draft `agent-policy.yaml`. |
| `scaffold.md` | How the agent generates the ArchUnit test class, the build wiring, and the CI snippet. |
| `operating.md` | Stack-specific operating-mode notes the agent reads when working in a Spring repo. |
| `adapter.yaml` | Tells the reporter where ArchUnit writes its output and what format it's in (JUnit XML). |

## Why ArchUnit

[ArchUnit](https://www.archunit.org/) is open source, JUnit-friendly, and built specifically for package-dependency rules. It analyzes compiled bytecode, so it finds real violations rather than textual matches. It drops in as one test class and integrates with the existing `./gradlew test` task.

Alternatives (jQAssistant, Spring Modulith, Semgrep) are reasonable for some teams but bring more weight or are less natural for layered architecture rules. This extension commits to ArchUnit; teams that need a different backend can fork the extension or build their own.

## Pointers

- agent-redline core: [../../README.md](https://github.com/rore/agent-redline/blob/main/README.md)
- How to build a different extension: [../../docs/EXTENSIONS.md](https://github.com/rore/agent-redline/blob/main/docs/EXTENSIONS.md)
- Policy schema: [../../docs/POLICY_SCHEMA.md](https://github.com/rore/agent-redline/blob/main/docs/POLICY_SCHEMA.md)
