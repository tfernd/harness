---
name: snowflake-cli
description: Safe use of the Snowflake CLI (`snow`) - name the connection, role and warehouse, read before writing, propose writes, deploy by project definition. Load before any `snow` command or a Snowflake connection setup.
---

# Snowflake CLI

SQL itself (DDL, dynamic tables, procedures, cost): `harness:code-sql`. No comments in files: `harness:comments`.

## Name everything

- Every call names its connection with `-c <name>`. Never rely on the default connection: it may be production.
- Name `--role` and `--warehouse` on a call that runs SQL, and `--database` and `--schema` where an unqualified name appears.
- First call in a session: `snow connection test -c <name>`. A failure stops the work; fix the connection, do not try another.

## Read first, propose writes

| Kind | Examples | Who runs it |
|---|---|---|
| Read | `snow sql -c <name> -q "select ... limit 20"`, `show ...`, `describe ...`, `snow object list <type>` | the agent |
| Write | DDL, DML, `snow stage copy` to a stage, `snow snowpark deploy`, `snow app deploy`, `snow app run`, `snow streamlit deploy` | the owner runs or approves it |

- Propose a write with the exact command and what it changes (objects created, replaced, dropped; rows touched; stage paths).
- A production connection is never used, even to read, without the owner's word.
- A read that could be large carries `LIMIT`; use `--format json` when a program parses the result.
- Check `snow <cmd> --help` for a flag before relying on it.
- SQL with quoted identifiers goes in a file run with `-f`, never nested in `-q`: the shell strips the inner quotes.
- Filter a large `SHOW` in SQL (`RESULT_SCAN(LAST_QUERY_ID())` with `WHERE`) or save it to a file; unfiltered it
  overflows the tool output.
- "Does not exist or not authorized" may be a missing grant, the wrong role, or the wrong environment's database: name
  the connection and role and run `SHOW GRANTS` before concluding the object is missing.

## Deploying

- Project definitions live in `snowflake.yml`; commands read it from the project folder. Edit the file, then deploy.
- Snowpark: `snow snowpark build`, then `snow snowpark deploy` (a write). Artifacts go to a stage the definition names.
- Repos: `snow git` commands work on a Git repository object in Snowflake; fetching it is a write.
- Apps and Streamlit: `snow app` and `snow streamlit` commands read their definition; deploy and run are writes.

## Credentials

- Key-pair or SSO (`authenticator = externalbrowser`) in `connections.toml` or `config.toml`. The folder is `$SNOWFLAKE_HOME`, else `~/.snowflake/` if it exists, else `~/.config/snowflake/` on Linux. `connections.toml` sits beside `config.toml` and wins for connections.
- Never a password on a command line, in an environment line a command prints, or in a file inside the repo.
- Add a new connection with `snow connection add` or by editing the user-level file; never commit it.

## What no tool checks

Whether a command is a read or a write when it runs a stored procedure or a `select` that calls a function with effects. Read the SQL; when unsure, treat it as a write.
