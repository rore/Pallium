# spring-archunit — scaffold

What bootstrap generates and how. Each section maps to one artifact.

By the time you reach this scaffold, `bootstrap-mode.md` Phase 3b has already tuned the policy against the repo's PR history (or noted that history was thin). Do not re-run the tuner here.

**Before generating any of this:** check whether the repo already has an ArchUnit test (search `src/test/**` for files importing `com.tngtech.archunit`). If found:

- Do NOT generate a new test class.
- Translate its existing rules into `boundaries:` entries in the policy. The policy's `boundaries:` are metadata the reporter surfaces; the existing test does the real enforcement.
- Skip §1 (dependency is already there) and §2 (test class exists).
- §3, §4, §5, §6 still apply — the existing test still produces JUnit XML the reporter reads, and CI / OpenAPI handling is independent.
- Tell the developer: existing test stays authoritative; the policy mirrors its rules so the agent and reporter understand them.

## 1. ArchUnit dependency

Add the JUnit 5 module to the build if absent. Pin to a known stable version.

**Gradle (Kotlin DSL):**
```kotlin
testImplementation("com.tngtech.archunit:archunit-junit5:1.3.0")
```

**Gradle (Groovy DSL):**
```groovy
testImplementation 'com.tngtech.archunit:archunit-junit5:1.3.0'
```

**Maven:**
```xml
<dependency>
    <groupId>com.tngtech.archunit</groupId>
    <artifactId>archunit-junit5</artifactId>
    <version>1.3.0</version>
    <scope>test</scope>
</dependency>
```

## 2. Architecture test class

Generate one `@ArchTest` method per `boundaries[]` entry in the policy. Test method name = boundary rule `id` (kebab-case → snake_case).

Substitute the actual base package and the actual layer package names from inspection. The example below uses placeholders (`domain`, `application`, `adapter`, `controller`); a repo using `core` / `infra` / `web` needs correspondingly different `resideInAPackage` arguments.

```java
// src/test/java/<base-package>/architecture/DependencyArchitectureTest.java

package <base-package>.architecture;

import com.tngtech.archunit.core.importer.ImportOption;
import com.tngtech.archunit.junit.AnalyzeClasses;
import com.tngtech.archunit.junit.ArchTest;
import com.tngtech.archunit.lang.ArchRule;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;

@AnalyzeClasses(
    packages = "<base-package>",
    importOptions = ImportOption.DoNotIncludeTests.class
)
class DependencyArchitectureTest {

    @ArchTest
    static final ArchRule domain_must_not_depend_on_adapters =
        noClasses()
            .that().resideInAPackage("..domain..")
            .should().dependOnClassesThat()
            .resideInAnyPackage("..adapter..");

    @ArchTest
    static final ArchRule application_must_not_depend_on_persistence_adapters =
        noClasses()
            .that().resideInAPackage("..application..")
            .should().dependOnClassesThat()
            .resideInAnyPackage("..adapter..persistence..");

    @ArchTest
    static final ArchRule controllers_must_not_access_repositories_directly =
        noClasses()
            .that().resideInAPackage("..controller..")
            .should().dependOnClassesThat()
            .resideInAnyPackage("..repository..", "..adapter..persistence..");
}
```

## 3. Test report output

ArchUnit produces JUnit XML through Gradle's default test reporting. Verify nothing has disabled it. Default location: `build/test-results/test/`. If the project writes elsewhere, update `outputPath` in the policy's adapter config.

## 4. CI snippet

Two flow modes — bootstrap-mode.md Phase 1 picks one:

- **PR-driven flow** — `on: pull_request:`; verdict surfaces via a sticky PR comment; enforce step fails CI on exit 2 only. The §6 OpenAPI block below shows this in full.
- **Push-driven flow** — `on: push: branches: [main]`; no sticky comment (no PR to comment on); verdict goes to a CI artifact + the workflow log; enforce step fails CI on exit 1 OR 2 (without a comment surface, exit 1 warnings need CI red as their visibility channel). The structural shape matches Python's scaffold.md §5b — adapt the install step for Gradle/Maven; the reporter call is identical.

The boundary job runs the same way in either mode:

```yaml
boundary:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-java@v4
      with:
        distribution: temurin
        java-version: '21'                     # match the repo's Java version
    - run: ./gradlew test --tests '*ArchitectureTest'
```

For Maven: replace the `run:` line with `mvn -B test -Dtest='*ArchitectureTest'`.

## 5. Baseline for retrofit cases

Run `./gradlew test --tests '*ArchitectureTest'` during Phase 1 inspection. If it fails on `main`, the rules will need the baseline pattern (capture existing violations, fail CI for new ones only). See [docs/CI_INTEGRATION.md](https://github.com/rore/agent-redline/blob/main/docs/CI_INTEGRATION.md) for the pattern; flag the affected rules in the CI proposal.

## 6. OpenAPI generation (optional)

If the repo uses SpringDoc with a generation plugin (`org.springdoc.openapi-gradle-plugin`), set `api.type: openapi-from-controllers` in the policy and add an `api` job to the CI proposal that produces the spec at base SHA and head SHA, then passes both to the reporter:

```yaml
api:
  runs-on: ubuntu-latest
  needs: report   # share the same checkout/setup
  steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0
    - uses: actions/setup-java@v4
      with:
        distribution: temurin
        java-version: '21'

    # Generate spec at head.
    - run: ./gradlew generateOpenApiDocs
    - run: cp build/openapi.json /tmp/spec_head.yaml

    # Generate spec at base via a worktree so we don't disturb the working tree.
    - run: |
        BASE_SHA="${{ github.event.pull_request.base.sha }}"
        git worktree add /tmp/base "$BASE_SHA"
        (cd /tmp/base && ./gradlew generateOpenApiDocs)
        cp /tmp/base/build/openapi.json /tmp/spec_base.yaml
        git worktree remove /tmp/base --force

    - name: Run reporter
      id: report
      # Capture the reporter's exit code without failing the step yet —
      # we want the sticky comment to post regardless. The "Enforce
      # reporter exit code" step below translates exit code 2
      # (binding-mode hard fail) into a step failure.
      #
      # Reporter exit codes:
      #   0  clean
      #   1  warnings (gray-zone, unmet checkpoint in shadow, watch-list
      #      touched, pr-size warn) — surfaces in the comment, does NOT
      #      block CI
      #   2  binding-mode hard fail (boundary violation, unsatisfied
      #      checkpoint under binding, pr-size fail under binding) —
      #      blocks CI
      #
      # Without the `set +e` + capture pattern, bash's default `-e` mode
      # makes ANY non-zero reporter exit fail the step. The comment
      # action and the enforce step never run, the verdict computes but
      # never reaches a human, and shadow mode's "surface, don't block"
      # contract silently breaks.
      run: |
        set +e
        # Compute the changed-files list at PR time.
        mkdir -p build
        git diff --name-only \
          ${{ github.event.pull_request.base.sha }}...${{ github.event.pull_request.head.sha }} \
          > build/changed-files.txt
        # The reporter reads policy.boundaryAdapter to find the ArchUnit
        # JUnit XML; for openapi-from-controllers it also takes the two
        # generated specs explicitly.
        python scripts/agent-redline-report.py \
          --policy agent-policy.yaml \
          --changed-files build/changed-files.txt \
          --api-spec-base /tmp/spec_base.yaml \
          --api-spec-head /tmp/spec_head.yaml \
          --pr-labels "$(jq -r '.pull_request.labels[].name' "$GITHUB_EVENT_PATH" | paste -sd,)" \
          --json-out build/verdict.json \
          --comment-out build/comment.md
        EXIT=$?
        echo "exit_code=$EXIT" >> "$GITHUB_OUTPUT"
        echo "--- verdict.json ---" && cat build/verdict.json
        echo "--- comment.md ---" && cat build/comment.md
        echo "reporter exit code: $EXIT"

    - name: Post sticky PR comment
      uses: marocchino/sticky-pull-request-comment@v2
      with:
        path: build/comment.md
        header: agent-redline

    - name: Enforce reporter exit code
      run: |
        EXIT="${{ steps.report.outputs.exit_code }}"
        if [[ "$EXIT" == "2" ]]; then
          echo "Reporter exited 2 (binding-mode hard fail). Failing the report check."
          exit 1
        fi
        echo "Reporter exited $EXIT — non-blocking."
```

The reporter consumes the two specs via `--api-spec-base` / `--api-spec-head` and computes a structural diff (paths added / removed, methods added / removed / modified). The output is a list of changed surface points; reviewers judge severity. The reporter does NOT classify breaking-vs-additive — false certainty there would be worse than no signal.

If the repo has no generation plugin, fall back to one of:

- `api.type: openapi-spec-file` if a spec is committed (path-diffed when the spec file changes).
- `api.type: none` if there's no public API surface.

In both fallbacks, controllers are still red-zone files via path classification, so an `api-review` checkpoint still fires. The structural diff is just absent.

Don't auto-add a generation plugin during bootstrap — it's a build change that needs human sign-off. Recommend it in the CI proposal if it would be useful.

The local pre-push check does NOT run the generation command (running two builds during a pre-push is hostile). It falls back to path classification — touched controllers are red and trigger api-review via the policy. The structural diff appears in CI; locally you see "you touched a controller." That asymmetry is by design.
