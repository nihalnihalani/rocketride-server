> Companion frontend PR: #2282 (`feat/sql-ui-workbench-upgrade-final`), which consumes the error text and the `refresh_schema` tool and degrades honestly when this PR is not deployed.

(backend) — branch `fix/db-node-execute-error-text` → `develop`


## Motivation
`_executeRawQuery` swallowed `SQLAlchemyError` and `execute` returned "SQL execution failed (check server logs for details)" — the driver's message never reached any caller. The node's schema cache (`IGlobal.db_schema`) is written once in `beginGlobal`, so DDL run through the node is invisible to `get_schema` and to the NL→SQL prompt until the task restarts.

## Changes
- **Execute error contract, both paths.** A failed `execute` raises `RuntimeError('SQL execution failed: <driver primary message>')` whether or not a `session_id` is passed. The session branch gained a `SQLAlchemyError` arm (above the broad `except`) that rolls the session back and releases it, then raises the formatted error; `tx_registry` is unchanged. The unreachable `result is None` branch is gone and `_executeRawQuery` is annotated `-> dict`. The max-rows overflow keeps its own `RuntimeError` wording and rollback. A cleanup failure during the rollback is logged and cannot mask the original error.
- **What the message contains.** SQLAlchemy's `[SQL: …]`/`[parameters: …]` tail, psycopg2's `LINE n:` echo, PostgreSQL DETAIL/HINT/CONTEXT/QUERY/STATEMENT blocks and ClickHouse's stack trace / `failed at position` echo are stripped; the driver's primary sentence is passed through. That sentence can quote the statement fragment at the error position or a value the statement carried or touched; the recipient holds `allow_execute` and could read the same data with a `SELECT`, which is the authorisation argument. The full exception stays in the server log.
- **New `refresh_schema` tool** (additive, no arguments): re-reflects the database under a module-level lock, replaces `IGlobal.db_schema`, invalidates the answers-lane column map (`IGlobal.schema`, rebuilt on the next insert) and returns the `get_schema` shape plus `refreshed_at`. One module-level `_format_table` now renders the per-table payload for both tools.
- **Lazy schema rebuild made safe.** `_insertData` holds `_REFLECT_LOCK` across the falsy check, the rebuild and a snapshot copy, and builds the batch from the snapshot; `_getTableSchema` and `_createTableFromData` build their maps locally and publish with one assignment, so a concurrent insert can never see a half-built map and a failed reflection leaves the previous map in place.
- **Generated primary keys per row.** Which primary-key columns the database generates is read from reflected metadata (`Table.autoincrement_column`, `server_default`, `identity`, explicit `autoincrement=True`), never assumed. Per row: an omitted generated key is left to the database, a supplied value is bound, an explicit NULL is bound as NULL. Rows are executed in contiguous runs of identical key sets inside one transaction (input order, row count and all-or-nothing behaviour unchanged). A row that omits a key the database does not generate is rejected with a `ValueError` before anything runs. A generated-only table gets a values-less `insert(table)`, rendered per dialect (`DEFAULT VALUES` on PostgreSQL/SQLite, `() VALUES ()` on MySQL) instead of a bound NULL.
- **READMEs** for db_mysql, db_postgres, db_clickhouse and rocketride_sql: full tool inventory, both schema caches described precisely, the questions-lane behaviour (only valid generated SQL is executed), the error contract, and no `answers` lane claimed for ClickHouse (it declares only `questions`).

## Testing
- `dist/server/engine -m pytest packages/ai/tests/database packages/ai/tests/ai/common/database` — **179 passed** (148 at the review head). New coverage: session-path error contract (type, no `[SQL:`/`[parameters:` tail, no bound value, session released, cleanup failure cannot mask), shared formatter and payload equality with FKs, deterministic barrier/event concurrency tests (concurrent insert during a rebuild, refresh overlapping a rebuild, auto-create fill, added and dropped columns, failed rebuild leaves the previous map, lock released), mixed supplied/generated keys, explicit NULL, composite and text keys rejected, batch failure rolls back every run, generated-only tables single and batch, per-dialect compilation of the default-values insert, psycopg2/pymysql/clickhouse-shaped exceptions through both paths.
- Whole `packages/ai/tests` — **2988 passed, 122 skipped** (pre-existing environmental skips). ruff check/format clean. `scripts/validate-node-readme.py` passes for the four nodes; `builder docs:validate` exit 0. CI: {CI}.
- **Not available locally:** PostgreSQL, MySQL, ClickHouse and their drivers. Cross-dialect behaviour is evidenced by compiling statements against the SQLAlchemy dialects and by constructing the drivers' documented exception shapes; the executed tests run on SQLite, which tolerates the NULL-into-`SERIAL` case the fixes prevent.

## Security note
Driver error text is exposed only to callers who hold `allow_execute`. Statement/parameter tails never leave the server log; the primary sentence is passed through and may quote a fragment of the statement or a value it touched (see "What the message contains"). The CodeRabbit security thread records the trade-off and is left open for the maintainers to accept or override.

## Compatibility
Additive tool; existing callers of `execute` see a more specific `RuntimeError` message with the same `SQL execution failed` prefix on both paths. The companion frontend (#2282) executes sessionless and degrades honestly when this PR is not deployed. **Conflict to be aware of:** #1908 (`feat/drizzle-over-pipes`, open, currently conflicting with develop) rewrites the same session `except` block with the opposite policy (keeps the session open on failure for savepoint recovery) and threads a `row_mode` argument through `_executeRawQuery`; whichever lands second must reconcile. Under SQLAlchemy's `'auto'` rule an Integer primary key that is also a foreign key is treated as caller-supplied.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01T4fLnswQF6yKQ6x7eWzSdd


<!-- This is an auto-generated comment: release notes by coderabbit.ai -->
## Summary by CodeRabbit

* **New Features**
  * Added a `refresh_schema` database tool to detect tables and schema changes made after startup.
  * The tool returns the current schema and a UTC refresh timestamp across supported database integrations.

* **Bug Fixes**
  * Database execution errors now show specific, sanitized driver messages without exposing SQL statements or parameters.
  * Inserts now correctly handle database-generated primary keys after schema refreshes.

* **Documentation**
  * Updated database integration guides with schema refresh and raw SQL tool details.

* **Tests**
  * Added coverage for schema refresh behavior, concurrent requests, dropped tables, and SQL error reporting.
<!-- end of auto-generated comment: release notes by coderabbit.ai -->
