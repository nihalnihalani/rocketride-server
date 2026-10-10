> Companion backend PR: #2283 (`fix/db-node-execute-error-text`). This frontend PR is correct and honest without it; with it, SQL errors show the driver text and Refresh re-reads the schema.

## Motivation
SQL Explorer could run only a whole editor buffer as one statement, swallowed every SQL error into "check server logs", offered no completion, history, or statement splitting, typed every result column as text, sorted the data browser only within the visible page, inlined numeric-looking filter values bare into SQL, and repainted a stale schema after every designer Apply (the node reflects its schema once at task start). MySQL Workbench was used as a research reference for everyday-SQL, schema-exploration, and diagnostics workflows; nothing MySQL-only was adopted.

## Scope
Frontend only (`apps/sql-ui`), plus a docs page and one lockfile line (`tsx` dev dependency). No shell package changes, no new runtime dependencies. A companion backend PR (`fix/db-node-execute-error-text`) surfaces driver error text and adds a `refresh_schema` tool; this PR is correct and honest without it.

## What changed
- **Runner:** run selection / statement at cursor (Ctrl/Cmd+Enter) or all statements in order with stop-on-error (Ctrl/Cmd+Shift+Enter); pre-run "Will run:" line + editor highlight; per-statement status strip (`ran` / `committed` / `failed` / `not run`); transaction-control statements refused (each statement autocommits on the node); pattern checks (labelled a text check) for UPDATE/DELETE without WHERE — including the outer statement of a `WITH` chain — an UPDATE/DELETE inside a `WITH` clause, `EXPLAIN ANALYZE` of any of these, TRUNCATE, DROP, ALTER, with a per-connection off switch; "Stop waiting" abandons a late response and states the statement may still be running.
- **Errors:** first line of the database's message as headline (the node's `SQL execution failed: ` wrapper is dropped from the headline, never from the verbatim block) + verbatim "Database said" block when the node returns it; explicit fallback sentence when the node returns the generic placeholder; allow_execute and max_execute_rows hints.
- **Results:** typed columns (schema or inferred, labelled), numeric alignment, cell inspector, three explicit limit states, export via the grid's existing gear menu.
- **Completion:** tables/columns/alias-scoped columns from the schema snapshot, FK-prefilled JOIN snippets, snapshot-age hint.
- **History:** per connection; search, filter, load into editor (replace confirm), rerun with a warning for write/DDL, pin, note, delete, clear, recording toggle; stored in the user's server-side workspace prefs (notice shown), bounded (100 incl. pins / 8 KB / 256 KB).
- **Relationships:** "Referenced by", join-path finder over declared foreign keys only (all shortest paths listed; composite, parallel, self-referential handled), generated previews (`Open as query`, `Select top 100`, `Count rows`) that never execute.
- **Insights page:** orientation (hubs/leaves/isolated) + snapshot-only review rules (no primary key, type strings differ, dangling foreign key), dialect-aware, limitations footer.
- **EXPLAIN drawer:** plain EXPLAIN only; raw output first; interpreted tree with `est.` on every planner number; parse miss shows raw + info banner.
- **Designer:** post-Apply banner says whether the schema was re-read (node with `refresh_schema`) or is still the task-start snapshot; Apply confirm lists inbound-FK impact and dialect commit semantics; no rollback wording.
- **Fixes to existing code:** data-browser filter values bound as `$n` parameters (were inlined; digit strings became numbers), remote sort reaches the SQL, page-load errors shown, SELECT/COUNT in parallel, `:`/`%` in table names survive URIs, Refresh re-reads when the node supports it, tool retry re-runs a statement only when marked idempotent.
- **Tests/docs:** `sql-ui:test` (node:test via tsx) with 496 pure-logic tests; new docs page `guides/apps/sql-explorer`.

## Before / after
| | Before | After |
|---|---|---|
| Run | whole buffer as one execute | selection / statement at cursor / all, per-statement outcomes |
| SQL error | "SQL execution failed (check server logs for details)" | driver text (with backend PR) or an honest fallback sentence |
| Completion | Monaco keywords only | schema tables/columns/aliases + snippets |
| History | none (lost on reload) | per-connection, bounded, server-side prefs, notice |
| Data browser sort | reordered the visible page only | ORDER BY sent to the database |
| Filters | `code >= 0100` (bare number) | `code >= $1` with `'0100'` bound |
| After designer Apply | stale schema repainted silently | explicit fresh/stale banner |

## Testing
- `./builder sql-ui:test` — **617 tests / 76 suites, all passing** across 20 files (pure-logic tests under node:test via tsx; splitter incl. `$tag$` bodies with non-ASCII tags, nested comments, quoting; classification and pattern checks incl. every `WITH` shape below; relations composite/self-ref/parallel; history bounds; EXPLAIN fixtures per dialect).
- `pnpm --filter @rocketride/sql-ui typecheck` and `typecheck:tests` — clean. `./builder sql-ui:build` — green. `./builder docs:build` — green, page renders.
- Review round 2026-09-15 (asclearuc's blocking finding + CodeRabbit's remaining findings): every change came with tests written first and shown failing on the previous code; an independent review and an adversarial review were run on the diff. CI: {CI}.
- **Not run:** no end-to-end session — this environment has no engine, database node, or shell dev server. EXPLAIN parsers are fixture-tested from vendor documentation only; ClickHouse parameter binding and error-text shape are unverified; Monaco wiring (single provider, decorations, keybindings) and the stop-waiting timer wiring are reasoned from the API and the run loop, not observed in a rendered test.

## Review round (2026-09-15)
- `patternCheck` reads the verb of a `WITH` chain: the outer statement's verb is the first top-level statement keyword after the chain (CTE names, with or without a column list, are skipped; PostgreSQL keeps `insert`/`update`/`delete`/`merge` non-reserved), so `WITH audit AS (SELECT id FROM orders) DELETE FROM orders` is confirmed as `DELETE without WHERE` while `SELECT … FOR UPDATE` and `INSERT … ON CONFLICT DO UPDATE` after a chain are not mislabelled. An UPDATE/DELETE that is the verb of a CTE body is reported as `<VERB> inside a WITH clause` — never "without WHERE", because a WHERE inside the clause cannot be attributed by a text check. `EXPLAIN ANALYZE <statement>` is checked as the statement it runs. `INSERT` is never flagged. Keyword boundaries use the SQL identifier character class (a `whereé` alias no longer reads as a WHERE). The remaining false positives are listed in the `patternCheck` docstring.
- PostgreSQL dollar-quote tags accept non-ASCII identifier characters (case-sensitive; digit-first rejected; `café$tag$` stays an identifier); `Straße'x'` is no longer read as an `E'…'` escape string.
- "Stop waiting" and its timer key on a statement actually being at the database, not on the batch running, so the button cannot appear while a confirmation dialog is open.
- The failure banner headline drops the node's `SQL execution failed: ` wrapper (the verbatim block keeps it).
- `scripts/tasks.js`: unused `ctx` renamed `_ctx`.

## Risks and limitations (documented in the docs page)
- allow_execute warning is per query document and clears on the next successful statement.
- `refresh_schema` capability latches off for the session after one failure (fallback is the task-start snapshot).
- Up to ~300 ms of history can be lost on an immediate app switch (writes only happen while SQL Explorer is the active app, to avoid writing into another app's prefs slice).
- The node rewrites `$n` textually; identifiers containing `$digits` are unsafe while filters are active (backend caveat).
- Monaco still loads from a CDN (pre-existing, shared with explorer-ui).
- QueryView grew to ~1,000 lines; a `useRunner` extraction is a recommended follow-up once a React renderer exists in the harness. Reviewers may prefer splitting Insights + EXPLAIN + designer notes into a follow-up PR; the commits are grouped to allow it.

## Rollback
Frontend-only; revert the merge. No data migration; history prefs are additive keys (`sql.history`, `sql.historyRecording`, `sql.patternChecks`) in the app's workspace prefs.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01T4fLnswQF6yKQ6x7eWzSdd


<!-- This is an auto-generated comment: release notes by coderabbit.ai -->
## Summary by CodeRabbit

- **New Features**
  - Added batch SQL execution with per-statement outcomes, safety checks, row limits, and clearer errors.
  - Added searchable query history with filters, pinning, notes, reruns, and recording controls.
  - Added EXPLAIN plans, schema-aware autocomplete, cell inspection, and copy actions.
  - Added schema Insights, relationship navigation, join previews, and table-design impact warnings.
  - Added accessibility announcements and improved keyboard interactions.

- **Bug Fixes**
  - Improved schema refresh reliability, stale-state reporting, paging stability, and parameterized filtering.

- **Documentation**
  - Added SQL Explorer user documentation.
<!-- end of auto-generated comment: release notes by coderabbit.ai -->
