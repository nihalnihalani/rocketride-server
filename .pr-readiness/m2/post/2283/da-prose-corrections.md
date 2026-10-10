# DA-F2/F3/F4/F7 prose corrections for #2283 (apply after the revision-2 push; edit in place, no duplicate comments)

## Summary comment 5680615643 (PATCH /issues/comments/5680615643)
- "plus an independent review, an adversarial review and a clean-state verification pass on the final head" -> "plus an independent review and a clean-state verification pass on each pushed head, and a dedicated adversarial pass whose final-revision verdict is recorded (its one high finding — ClickHouse's native connector bypassing the error formatting — was taken in the last push)"
- Update head SHA, commit count, test counts, CI run; add the three maintainer notes + DA-F1 to the list of what the last push contains.

## Description (PATCH /pulls/2283)
- Testing: "psycopg2/pymysql/clickhouse-shaped exceptions through both paths" -> "psycopg2- and pymysql-shaped exceptions through both paths; ClickHouse's `DatabaseException` shape (plain Exception carrying `.orig`) through both paths via a stand-in class (driver not installed)"; update counts and CI run.
- Changes: add the revision-2 items (server-default columns left to the database after a refresh; explicit null on a generated key treated as omitted on the answers lane; `params` validated; unreachable branch removed) and the ClickHouse arm.
- Compatibility/limitations: note DA-F6's pre-existing behaviour is now validated up front; keep the #1908 note.

## Thread replies (PATCH /pulls/comments/{id})
- r4015863646 (B2): "existing tests untouched" -> "existing assertions kept; `test_refresh_schema_matches_get_schema_shape` was strengthened to reflect a primary key and a foreign key".
- r4015862345 (B7): "that is a one-line change in `_format_db_error`" -> "that is a small change at the two `execute` call sites that format the message (not in `_format_db_error` itself, which `validateConfig` also uses for save-time diagnostics)"; append one sentence: the ClickHouse claim was wrong at the time of this reply — the native connector's exception is not a SQLAlchemyError — and is fixed in {SHA} with a test.
- New replies for r4017571001, r4017571014, r4017571022 (maintainer's three notes) with commit + tests.
