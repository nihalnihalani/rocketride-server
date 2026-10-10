#!/usr/bin/env python3
"""Publish round 2 for PR #2283: reply to the maintainer's three notes, correct earlier texts in place,
update the summary and description, re-request review. Usage: apply-r2.py <full_sha> <ci_run_id>"""
import json, os, re, subprocess, sys, tempfile

REPO = 'rocketride-org/rocketride-server'
SHA, RUN = sys.argv[1], sys.argv[2]
SHORT = SHA[:8]
LINK = f'[run {RUN}](https://github.com/{REPO}/actions/runs/{RUN})'
HERE = os.path.dirname(os.path.abspath(__file__))
LOG = open(os.path.join(HERE, 'published.md'), 'a')


def gh(method, path, body=None):
    args = ['gh', 'api', '-X', method, path]
    tmp = None
    if body is not None:
        tmp = tempfile.NamedTemporaryFile('w', delete=False, suffix='.json')
        json.dump(body, tmp, ensure_ascii=False)
        tmp.close()
        args += ['--input', tmp.name]
    out = subprocess.run(args, capture_output=True, text=True)
    if tmp:
        os.unlink(tmp.name)
    if out.returncode != 0:
        raise SystemExit(f'{method} {path} failed: {out.stderr}')
    return json.loads(out.stdout) if out.stdout.strip() else {}


def must_replace(text, old, new):
    if old not in text:
        raise SystemExit(f'expected phrase not found: {old[:70]}')
    return text.replace(old, new)


def reply(root_id, body):
    res = gh('POST', f'repos/{REPO}/pulls/2283/comments/{root_id}/replies', {'body': body})
    LOG.write(f'- reply to {root_id} -> {res.get("id")} {res.get("html_url")}\n')


# 1. Replies to the maintainer's three notes.
reply(4017571001,
      f'Addressed in 76d83a32 (head `{SHORT}`), with your fix as written: `generated_defaults` is read from the reflected table (`server_default` or `identity` on any column) and an omitted such column is left to the database, next to the generated primary keys; a supplied value still wins. Your scenario reproduced end to end on SQLite before the change (`NOT NULL constraint failed: answers.created_at` with `None` bound) and is now `test_insert_leaves_a_new_not_null_default_column_to_the_database` (auto-create, `ADD COLUMN created_at … NOT NULL DEFAULT`, `refresh_schema`, insert without it → both rows hold the default), with `test_insert_binds_a_supplied_value_over_a_server_default` and `test_insert_still_binds_null_for_an_omitted_column_without_a_default` pinning the edges. Both comments you pointed at are rewritten: they no longer claim the invalidation cannot change the lane — changing the INSERT is the point of a refresh — and they state the guarantee that holds (what the database owns, it still fills in), including the supplied-key asymmetry on an auto-created table that the adversarial pass flagged.')
reply(4017571014,
      f'Addressed in 76d83a32 (head `{SHORT}`): an explicit `None` on a database-generated key is treated as omitted (`continue`), so `"id": null` from an upstream node lets the database generate the key instead of binding NULL into a `SERIAL`. `test_insert_binds_an_explicit_null_primary_key_the_caller_supplied` is replaced by `test_insert_leaves_an_explicit_null_generated_key_to_the_database` (no `id` column in the captured INSERT, `parameters == [\'a\']`, the row gets a generated id); `test_insert_still_binds_an_explicit_null_on_a_non_key_column` keeps the scope narrow and `test_insert_still_binds_a_primary_key_the_rows_do_supply` is unchanged. The rule is stated in the `_generated_primary_keys` docstring, the loop comment, and the insert-lane prose of the three READMEs that declare an `answers` lane (db_clickhouse declares none). The `execute` tool is unaffected — raw SQL binds what it is given.')
reply(4017571022,
      f'Addressed in 76d83a32 (head `{SHORT}`): the `else:` "no schema cached" branch and the `if schema:` guard are deleted (the locked block leaves a populated snapshot or raises), and the lock rationale keeps only the half-built-map half that `test_a_concurrent_insert_waits_for_the_schema_rebuild` proves.')

# 2. In-place corrections to earlier replies (DA-F4, DA-F7 + the ClickHouse correction).
r = gh('GET', f'repos/{REPO}/pulls/comments/4015863646')
body = must_replace(r['body'], 'existing tests untouched',
                    'existing assertions kept; `test_refresh_schema_matches_get_schema_shape` was strengthened to reflect a primary key and a foreign key')
gh('PATCH', f'repos/{REPO}/pulls/comments/4015863646', {'body': body})
LOG.write('- corrected reply 4015863646 in place (DA-F4)\n')

r = gh('GET', f'repos/{REPO}/pulls/comments/4015862345')
body = must_replace(r['body'], 'that is a one-line change in `_format_db_error` — leaving this thread open for that call.',
                    'that is a small change at the two `execute` call sites that format the message (not in `_format_db_error` itself, which `validateConfig` also uses for save-time diagnostics) — leaving this thread open for that call.')
body += (f'\n\n**Correction ({SHORT}):** the ClickHouse claim above was wrong at the time it was written. The db_clickhouse node connects with `clickhouse+native://`, whose connector raises a plain-`Exception` `DatabaseException` carrying the driver error in `.orig`; SQLAlchemy never wraps it, so neither `except SQLAlchemyError` arm ran for ClickHouse and the raw text, stack trace included, reached the caller (the adversarial pass reproduced this with the pinned clickhouse-sqlalchemy 0.3.2 + clickhouse-driver 0.2.9). 5d20c78e adds an arm on both paths for an exception that carries `.orig`, renders `Error <code>: <message>` from the server error, and strips the stack trace and `failed at position` echo; `test_both_paths_format_a_driver_error_sqlalchemy_did_not_wrap[sessionless|session]` and `test_an_exception_without_orig_is_not_treated_as_a_database_error[…]` pin it with a stand-in shaped like that exception (driver not installed here). The two earlier ClickHouse formatter tests are relabelled as the DBAPI layer this node does not use.')
gh('PATCH', f'repos/{REPO}/pulls/comments/4015862345', {'body': body})
LOG.write('- corrected reply 4015862345 in place (DA-F7) and appended the ClickHouse correction (DA-F1)\n')

# 3. Summary comment: correct DA-F2 and update for the last push.
s = gh('GET', f'repos/{REPO}/issues/comments/5680615643')
body = s['body']
body = must_replace(body, 'and an independent review, an adversarial review and a clean-state verification pass on the final head',
                    'and an independent review and a clean-state verification pass on each pushed head, plus a dedicated adversarial pass whose final-revision verdict is recorded (its one high finding — the ClickHouse native connector bypassing the error formatting — was taken in the last push)')
COUNT = subprocess.run(['git', '-C', '/Users/nihalnihalani/Desktop/Github/rr-work/pr2283', 'rev-list', '--count', f'28c461e3b882f378b58d172b0596249ffd522e3b..{SHA}'], capture_output=True, text=True).stdout.strip()
body = must_replace(body, 'pushed 10 commits on top of `28c461e3` (head `de71b048`)', f'pushed {COUNT} commits on top of `28c461e3` (head `{SHORT}`)')
body = must_replace(body, 'Verified: 179 passed in the two database directories with the built engine (148 before), whole `packages/ai/tests` 2988 passed / 122 environmental skips',
                    'Verified: 194 passed in the two database directories with the built engine (148 before), whole `packages/ai/tests` 3003 passed / 122 environmental skips')
body = re.sub(r'`CI OK` on `de71b048`: \[run \d+\]\(https://github\.com/[^)]+\)', f'`CI OK` on `{SHORT}`: {LINK}', body)
body += (f'\n\n**Update ({SHORT}):** your three notes are taken as written (server-default columns left to the database after a refresh, an explicit null on a generated key treated as omitted on the answers lane, the unreachable branch removed), plus two items from the adversarial pass on the final head: the ClickHouse native connector\'s exception is now formatted on both paths, and a malformed `params` argument is rejected with a clear `ValueError` instead of being misreported as an expired session. The push dismisses your approval automatically; a re-stamp when you have a moment would unblock the merge.')
gh('PATCH', f'repos/{REPO}/issues/comments/5680615643', {'body': body})
LOG.write('- summary 5680615643 corrected (DA-F2) and updated in place\n')

# 4. Description: accuracy fixes (DA-F3) and the round-2 items.
pr = gh('GET', f'repos/{REPO}/pulls/2283')
body = pr['body']
body = must_replace(body, "ClickHouse's stack trace / `failed at position` echo are stripped",
                    "ClickHouse's stack trace / `failed at position` echo are stripped (the `clickhouse+native://` connector raises a plain `Exception` carrying the driver error in `.orig`, so both paths also handle that non-SQLAlchemy shape)")
body = must_replace(body, 'psycopg2/pymysql/clickhouse-shaped exceptions through both paths',
                    'psycopg2- and pymysql-shaped exceptions through both paths, and a stand-in shaped like the ClickHouse connector\'s `DatabaseException` through both paths (driver not installed here)')
body = must_replace(body, '**179 passed** (148 at the review head)', '**194 passed** (148 at the review head)')
body = must_replace(body, '**2988 passed, 122 skipped**', '**3003 passed, 122 skipped**')
body = re.sub(r'CI: \[run \d+\]\(https://github\.com/[^)]+\)', f'CI: {LINK}', body)
body = must_replace(body, '- **READMEs** for db_mysql, db_postgres, db_clickhouse and rocketride_sql:',
                    '- **After the approval notes.** On the answers lane an omitted column with a server default or identity is left to the database (an explicit supplied value still wins), and an explicit `null` on a database-generated key is treated as omitted — the caller there is an upstream node, so `"id": null` means "no value"; the `execute` tool binds exactly what it is given. A `params` argument that is not an array, or that does not cover every `$n` placeholder, is rejected with a clear `ValueError` on both paths instead of surfacing as a bare `KeyError` or a false "unknown or expired session".\n'
                    '- **READMEs** for db_mysql, db_postgres, db_clickhouse and rocketride_sql:')
body = must_replace(body, "Under SQLAlchemy's `'auto'` rule an Integer primary key that is also a foreign key is treated as caller-supplied.",
                    "Under SQLAlchemy's `'auto'` rule an Integer primary key that is also a foreign key is treated as caller-supplied. Two limitations recorded by the adversarial pass and left as-is: a `begin` connection failure still reaches the caller unformatted (pre-existing; one-line follow-up), and because omitted server-default columns now receive their default, a schema such as `slug TEXT UNIQUE DEFAULT ''` collides on the second row where NULLs did not — the trade-off the maintainer chose; every other direction improves. The `get_data` path (`_executeSQLQuery`) still catches only `SQLAlchemyError`, so on ClickHouse it raises instead of returning `{valid: false, error}` (pre-existing; follow-up).")
gh('PATCH', f'repos/{REPO}/pulls/2283', {'body': body})
LOG.write('- description updated (DA-F3 wording, counts, CI, round-2 items)\n')

# 5. Re-request the reviewer whose approval the push dismisses.
res = gh('POST', f'repos/{REPO}/pulls/2283/requested_reviewers', {'reviewers': ['asclearuc']})
LOG.write(f'- re-requested: {[u["login"] for u in res.get("requested_reviewers", [])]}\n')
LOG.close()
print('round 2 published for #2283')
