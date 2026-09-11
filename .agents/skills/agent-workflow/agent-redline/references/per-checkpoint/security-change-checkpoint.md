# security-change-checkpoint

You're here because you're touching security-sensitive code: authentication, authorization, JWT handling, secrets, crypto, security configuration. The base checkpoint-note format is in `operating-mode.md`. This doc adds what to think about specifically for security changes.

## Authentication vs. authorization

Both go through `security-review` but the failure modes differ.

- **Authentication change:** who can log in, how identity is established, session/token lifecycle. Wrong = unauthorized access.
- **Authorization change:** what an authenticated principal can do, role/permission checks, resource ownership. Wrong = privilege escalation.

State which one this is in the checkpoint note. Reviewers think about them differently.

## Never include in a checkpoint note

- Secret values (tokens, passwords, keys), even examples or placeholders that look like real secrets
- Production credentials, even partially masked
- The exact crypto key names if they could narrow an attack surface

If the change requires referencing a secret, refer to it by *name and location* (env var name, secret-manager key), never by value.

## Don't loosen "in passing"

A security change is small only when it's narrowly scoped. Watch for incidental loosening:

- Adding `permitAll()` to a previously-restricted route while doing other work
- Changing `@PreAuthorize` from a specific role to a broader one
- Disabling CSRF or CORS for a route that was protected
- Lowering a token's required scope or audience

If your change touches any of these, that's the focus of the checkpoint, not whatever else is in the PR. Surface it explicitly.

## What the reviewer needs to know

- The exact set of routes / operations whose access changed
- The before/after principal scope (anonymous → authenticated, role X → role Y, etc.)
- Whether anything *was* protected and is now not (the most consequential class of change)
- Whether a test was added that fails on the *old* behavior

## Don't include

- Full security configuration files (the diff suffices)
- Restated authentication or framework concepts
- Unrelated cleanup (security PRs are not the place)
