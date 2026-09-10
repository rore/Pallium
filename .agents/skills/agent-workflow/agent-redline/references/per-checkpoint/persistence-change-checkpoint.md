# persistence-change-checkpoint

You're here because you're touching the persistence contract: migrations, schemas, entity mappings. The base checkpoint-note format is in `operating-mode.md`. This doc adds what to think about specifically for persistence changes.

## Classify the change shape

- **Schema-only:** structural changes to tables, columns, indexes, constraints. No data is rewritten.
- **Data migration:** existing rows are modified, copied, or deleted as part of the migration.
- **Index change:** added, removed, or rebuilt indexes. Performance impact depends on table size.
- **Combined:** schema + data migration in one step. Hardest to roll back; surface this explicitly.

State the shape in the checkpoint note. Reviewers look at "data migration" and "combined" much more carefully than "schema-only."

## Forward-only assumption

Migrations apply forward; rollback usually means a new compensating migration, not undoing the first one. The checkpoint note must state:

- **What rolls back cleanly:** drop column, drop table, drop index. These can be undone with the inverse.
- **What does not roll back:** data migrations that lose information, type changes that truncate, constraint additions that filtered out rows. Once shipped, the prior state is unrecoverable.

If the change is in the second category, the checkpoint note should include the recovery plan (backup, replay, etc.) — not the rollback plan.

## Existing migrations are immutable

Never edit a `V*.sql` file already on `main`. To change V1, write V2 that compensates — e.g., `ALTER TABLE ... ADD COLUMN` for a missed column, a follow-on migration for a wrong type. Listed as a refusal pattern in `operating-mode.md`.

## Index changes have hidden cost

`CREATE INDEX` on a large table can lock writes for minutes or longer depending on the database. The checkpoint note must address:

- Estimated table size at deploy time
- Whether the database supports concurrent index creation (`CREATE INDEX CONCURRENTLY` on Postgres) and whether the migration uses it
- Whether the deploy can tolerate the lock duration

Index changes look small in the migration file. Their cost is operational, not structural.

## Multi-tenant rollout

If the policy declares multi-tenant persistence (`persistence.notes` mentions per-tenant migrations), every checkpoint note must include the rollout plan: which tenants migrate first, how long the canary runs, how a failed tenant rolls back without affecting others. A schema diff alone is not sufficient.

## Don't include in the checkpoint note

- The full migration SQL (the reviewer reads the diff)
- ORM-generated boilerplate
- Restated requirements
