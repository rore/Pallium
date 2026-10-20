# node — profile

Zone-only defaults for Node, JavaScript, and TypeScript. This is guidance, not a detector: derive candidate paths from tracked project files and confirm them with the developer in Phases 1 and 3.

## Phase 1 evidence

Select this profile when an owned root, nested package, or workspace `package.json` is tracked; package scripts referenced by CI also show ownership. Ignore manifests under vendored, generated, or test-fixture trees for selection; do not exclude those paths from policy. If another ecosystem also has an owned build manifest, show both candidates and ask the developer. With no owned manifest, use the existing fallback.

Inspect each project manifest's `scripts`, `exports`, `bin`, `main`, and `types`; workspace declarations; `tsconfig*.json`; test and lint configuration; actual source, test, generated, and mirror paths; package-manager lockfiles; and scripts referenced by CI. Do not infer that UI or JavaScript implementation is low risk from its language or directory name.

When paired with agent-workflow bootstrap, propose every owned code root for `hooks.guardedPaths`, including roots whose files remain gray under Redline; use the shared Phase 2 layout guidance.

## Candidate zones

| Zone | Propose only from observed evidence |
|---|---|
| Red | Security/authentication/authorization code; migration or persistence contracts; published entry points (`exports`, `bin`, `main`, or `types` targets); observed source-write guards, atomic multi-file apply/rollback, checkout identity, server lifecycle, or shared contracts; explicit dependency-boundary rules; protected contract or architecture tests, including tests under a test tree |
| Blue | Narrow unit tests without protected contracts; non-contract docs; local tooling with no release or deployment role. Leave canonical docs for shared behavior-contract discovery. |
| Watch | Package manifests and locks; compiler, bundler, test, lint, and CI configuration; generated sources, generated declarations, and checked-in mirrors |
| Gray | Everything not supported by repository evidence |

Use exact paths and the repository's actual layout. Watch is additive: manifests, locks, generated files, and mirrors remain classified red, blue, or gray. Preserve generated-mirror parity checks. Never add broad test, generated, lockfile, or JavaScript exclusions. Do not make all UI, source, or tests blue.

## Boundary capability and PR size

No Node boundary backend is shipped. Set `boundaryAdapter: { outputFormat: none }`, omit `boundaries`, and say that import boundaries are not configured. Do not claim enforcement from TypeScript, ESLint, or a test command unless an existing repository tool actually enforces the named rules.

```yaml
prRules:
  maxChangedFiles: { warn: 30, fail: 80 }
  maxLinesChanged: { warn: 800, fail: 1500 }
```
