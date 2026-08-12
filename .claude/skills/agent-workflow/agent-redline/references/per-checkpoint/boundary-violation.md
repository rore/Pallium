# boundary-violation

You're here because the boundary-rule backend reported a forbidden import, or because your intended change would create one. The base rules (refuse the workaround, fix the structure or escalate) are in `operating-mode.md`.

## Fix the structure

If a port or interface needs to change, the structural fix is itself a red-zone change — usually `architecture-review`. Concrete steps:

1. **Identify what's missing.** What method, port, or interface would make the dependency legitimate? Name it.
2. **Propose its shape.** Write the new method signature or interface in the checkpoint note. Include the abstraction's contract (preconditions, return type, failure modes).
3. **Get the architecture-review checkpoint** before implementing.
4. **Implement the fix as its own PR** if non-trivial. Don't bundle it with the work that triggered it — that mixes "expand the architectural surface" with "use the new surface."
5. **Return to the original task** once the structural fix has merged.

When the structural fix is trivial (one method on an existing port, no contract change), it can ride with the original PR, but the checkpoint note must still call it out explicitly.

## Escalate

If you can't propose a structural fix (the missing abstraction isn't obvious; the design isn't clear), do not invent one. Tell the developer:

```
This change requires a modeling decision I can't make alone:
- Original task: <what was asked>
- Boundary rule violated: <rule id>
- Why a simple fix isn't obvious: <one sentence>
- What needs to be decided: <the design question>
```

Then stop. Wait for the developer's call.

## Patterns to refuse

- **"This import is just for tests."** The rule applies to all imports. If a test needs it, the test is at the wrong layer or the abstraction is missing.
- **"This dependency already exists elsewhere."** That's the baseline the rule allows. It does not justify a *new* one. Existing violations are managed via the baseline file.
- **"This is temporary, I'll fix it later."** No mechanism tracks it. Add to the baseline explicitly if it must ship now, or escalate.
- **"The rule is too strict."** That's a policy edit. Refused as a side-effect — see `operating-mode.md` "Do not silently modify governance." Fix the structure or escalate.
- **"It's just one line."** Lines aren't the issue. The forbidden dependency is.

## Suppressions

Adding `# noqa`, `# type: ignore`, `@SuppressWarnings`, `@ArchIgnore`, `ignore_imports`, or `per-file-ignores` on a non-exempt path. Responses above apply. Refuse:

- **"Just for tests."** If the path isn't in `exemptPaths`, it isn't tests.
- **"I'll remove it later."** Nothing tracks it.
- **"The linter is wrong."** File an issue; don't suppress.
- **"One suppression to ship."** Editing `exemptPaths` is itself red-zone.