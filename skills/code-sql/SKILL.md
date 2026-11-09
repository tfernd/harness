---
name: code-sql
description: Snowflake SQL and dbt rules - style, idempotent DDL that never drops table data, grants, tasks, dynamic tables, procedures and UDFs, Snowpark ML, cost, check queries, dbt targets and builds. Load before writing, moving or reviewing any .sql file or dbt project file.
---

# Snowflake SQL

No comments or docstrings: `harness:comments`. The `snow` CLI: `harness:snowflake-cli`.

## Style

- Uppercase keywords, lowercase snake_case names, one clause per line, one column per line.
- Explicit column lists: no `SELECT *` in a view, dynamic table or `INSERT`.
- CTEs over nested subqueries; name each CTE for what it holds.
- Qualified names (`db.schema.object`) in deploy scripts, so a script never depends on the session's current schema.
- One object per file in a deploy folder, named for the object.

## Idempotent DDL

A script runs twice with the same result.

| Object | Statement |
|---|---|
| Table that holds data | `CREATE TABLE IF NOT EXISTS`; change it by `ALTER TABLE`; `CREATE OR ALTER TABLE` is a write that needs the owner's word, since a column it drops loses its data |
| Schema, database, stage, warehouse, role | `CREATE ... IF NOT EXISTS` |
| View, function, procedure, dynamic table | `CREATE OR REPLACE`; grants are lost unless `COPY GRANTS` |
| New or empty tables, dynamic tables, views, functions, procedures, schemas, stages, streams, tasks, tags | `CREATE OR ALTER` alters in place; a column it drops loses its data |

- Never `CREATE OR REPLACE TABLE` on a table that holds data: it is a DROP then a CREATE. The data is gone from the live table (recoverable only through Time Travel within retention, by undrop or rename), streams on it go stale, and grants are lost unless `COPY GRANTS`.
- `CREATE OR REPLACE DYNAMIC TABLE` keeps the old table until the new one exists, then the new one runs its initial refresh (`INITIALIZE = ON_CREATE` by default): a full recompute, and its cost.
- `DROP`, `TRUNCATE` and `DELETE` without `WHERE` only with the owner's word, said in this job.
- `UPDATE` and `DELETE` carry a `WHERE`; run its `SELECT COUNT(*)` first and state the count expected.
- Grants are per role, and repeatable (`GRANT` twice is a no-op); an object grant also needs `USAGE` on its database and
  schema. `REVOKE` is a change, treat it like a `DROP`.
- A script that creates a schema or objects grants on both `ALL` and `FUTURE` schemas (or objects) in the same script,
  so objects made later are covered.
- A task is created suspended; resuming it is a separate step the owner runs, child tasks before the root. Name the schedule's timezone.
- A destructive macro or script checks the target and database first, names the objects it drops, and makes
  "everything" an explicit flag.

## dbt

- Read the dbt and adapter versions pinned in the repo; never pick one.
- A green `dbt parse` or compile is not a pass: build the changed models on the dev target before calling them done.
- dbt commands name their target (`--target`); a non-dev target (ci, stage, prod, any shared one) runs only on the
  owner's word in this job.
- Check the env vars a profile needs before the first dbt call.
- On a failure, read the failing model and its SQL in `logs/dbt.log`, not the console summary.
- "Two resources with the same database representation" or a duplicate schema entry means a model or YAML entry is
  defined twice: search for the name.
- Read tables through `ref` or `source`, never an assumed schema: schema naming differs by target.
- An existing table is declared as a source, never copied as a model.
- Business constants go in `vars`, not SQL literals.
- A change to a model's contract edits its YAML in the same change as the column.
- An ephemeral model takes no test: test the next materialised model, or write a singular test.
- Report a deprecation warning, and fix it when the change touches that file.
- Check a seed file's delimiter and line endings before its first build.

## Dynamic tables

- `TARGET_LAG` chosen from the consumer's need, not the smallest allowed; a shorter lag costs more refreshes.
- `WAREHOUSE` named, sized to the refresh.
- `REFRESH_MODE` is `AUTO` (default), `INCREMENTAL` or `FULL`. `AUTO` resolves once at creation and never re-evaluates, so set `INCREMENTAL` explicitly when you need it; creation fails if the query cannot be incremental.
  Check the mode in use with `SHOW DYNAMIC TABLES` and the refresh history (`TABLE(INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY(...))`), not by assumption.
- `RANDOM()` and `UUID_STRING()` in the select list force a full refresh; current-time functions are supported only in `WHERE`, `HAVING` and `QUALIFY`.
- A table that feeds another dynamic table: `TARGET_LAG = DOWNSTREAM`, so only the last one sets the pace.
- An explicit column list in the defining query: a source column added later does not change the table by surprise.

## Procedures and UDFs

- `LANGUAGE` named (`SQL`, `PYTHON`, `JAVASCRIPT`, `JAVA`, `SCALA`).
- `EXECUTE AS OWNER` or `CALLER` chosen on purpose: `OWNER` runs with the owner's rights (grant `USAGE` narrowly);
  `CALLER` runs with the caller's. Write it out, never rely on the default.
- Arguments bound: `:name` in Snowflake Scripting, `?` with `USING` in `EXECUTE IMMEDIATE`. Never build SQL by concatenating input.
  An identifier that must vary goes through `IDENTIFIER(:name)`, after a check against an allowed list.
- Errors raised: `RAISE` or `RETURN` an error status; a `WHEN OTHER` handler that swallows the error is a bug.
- A procedure that changes data is idempotent (`MERGE` over `INSERT`), so a retry does not duplicate rows.
- Python handlers: pin `RUNTIME_VERSION` and list `PACKAGES`. A NULL argument is checked explicitly; how it reaches the
  handler differs by type and handler language, so test the NULL case.
- A function name the warehouse does not have fails only at build: check the docs.
- A changed procedure signature leaves the old overload: drop it by its full signature.

## Snowpark ML and the model registry

- Features are built in SQL or Snowpark, in a view or dynamic table, not in an ad hoc local frame.
- A trained model is logged to the model registry as a named, versioned model; never a pickle on a stage.
- Inference calls the registry model (`MODEL(...)!PREDICT` or the registry's Python `run`), by version or default alias chosen on purpose.
- Training data and the model version it produced are recorded together (a table row or version metadata).
- The exact registry API and method names change between `snowflake-ml-python` versions: read the installed version's source before writing the call.

## Cost

- Filter early: `WHERE` on the large table before joins; select only needed columns.
- `LIMIT` in exploration; a sample (`SAMPLE`) over a full scan when the question allows.
- Cluster keys only when measured (partition pruning in the query profile shows scans of most partitions); they add maintenance cost.
- The warehouse sized to the job: start `XSMALL`, step up only when the profile shows spilling to disk.
- `AUTO_SUSPEND` set on a warehouse you create.
- Read the query profile before tuning: a guess is not a measure.

## Tests

- Each change ships a check query with an expected result: row count, a null-count of zero on a key, a duplicate-key count of zero, or a value reconciled against the source.
- The check is a `SELECT` that returns no rows or one known row, so a failure is visible without reading output.
- A change to a dynamic table is checked after a refresh, with the refresh history shown.
- Propose running a destructive change first in a clone (`CREATE TABLE ... CLONE`) or a dev schema.

## What no tool checks

Whether a statement is safe for data already in the table, whether the lag and warehouse fit the need, whether a handler's rights are as narrow as they can be, and whether a check query can fail.
