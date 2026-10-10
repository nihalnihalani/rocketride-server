#!/usr/bin/env python3
"""apply-desc-r2.py <pr> <full_sha> <ci_run_id> [COUNTS=...] — in-place description updates for the round-2 sync.
Every replacement is exact-phrase (must_replace) so a changed description fails loudly instead of silently."""
import json, os, re, subprocess, sys, tempfile

REPO = 'rocketride-org/rocketride-server'
PR, SHA, RUN = sys.argv[1], sys.argv[2], sys.argv[3]
extra = dict(a.split('=', 1) for a in sys.argv[4:])
SHORT = SHA[:8]
LINK = f'[run {RUN}](https://github.com/{REPO}/actions/runs/{RUN})'
HERE = os.path.dirname(os.path.abspath(__file__))


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
        raise SystemExit(f'expected phrase not found: {old[:80]}')
    return text.replace(old, new)


pr = gh('GET', f'repos/{REPO}/pulls/{PR}')
body = pr['body']

if PR == '2283':
    body = must_replace(
        body,
        'The session branch gained a `SQLAlchemyError` arm (above the broad `except`) that rolls the session back and releases it, then raises the formatted error; `tx_registry` is unchanged.',
        'The session branch gained a `SQLAlchemyError` arm (above the broad `except`) that raises the formatted error; since the merge with `develop` @ `1339a081` (#1908) a failed statement leaves the session open — `rollback` / `rollback to savepoint` recover it and the registry refuses to commit an aborted transaction — so no release happens on this path.',
    )
    body = must_replace(
        body,
        'A cleanup failure during the rollback is logged and cannot mask the original error.',
        'The `row_mode` argument from #1908 is threaded through `_executeRawQuery`.',
    )
    body = must_replace(
        body,
        'A `params` argument that is not an array, or that does not cover every `$n` placeholder, is rejected with a clear `ValueError` on both paths instead of surfacing as a bare `KeyError` or a false "unknown or expired session".',
        'A `params` argument that is not an array is rejected with a clear `ValueError` on both paths instead of surfacing as a bare `KeyError` or a false "unknown or expired session"; the `$n` range check is `to_sqlalchemy_text`\'s (quote-aware since #1908, so a `$n` inside a string literal is not a placeholder).',
    )
    body = must_replace(
        body,
        'New coverage: session-path error contract (type, no `[SQL:`/`[parameters:` tail, no bound value, session released, cleanup failure cannot mask),',
        'New coverage: session-path error contract (type, no `[SQL:`/`[parameters:` tail, no bound value, session left open for the client\'s rollback),',
    )
    body = re.sub(r'— \*\*\d+ passed\*\* \(148 at the review head\)', f'— **{extra.get("DBCOUNT", "238")} passed** (148 at the review head)', body)
    body = re.sub(r'\*\*\d+ passed, 122 skipped\*\*', f'**{extra.get("AICOUNT", "3010")} passed, 122 skipped**', body)
    body = re.sub(r'CI: \[run \d+\]\(https://github\.com/[^)]+\)', f'CI: {LINK}', body)
    body = must_replace(
        body,
        '**Conflict to be aware of:** #1908 (`feat/drizzle-over-pipes`, open, currently conflicting with develop) rewrites the same session `except` block with the opposite policy (keeps the session open on failure for savepoint recovery) and threads a `row_mode` argument through `_executeRawQuery`; whichever lands second must reconcile.',
        f'**Merged with #1908** (`develop` @ `1339a081`, merge commit on this branch, head `{SHORT}`): the session-after-error policy is #1908\'s (session stays open), the error text is unchanged and identical on both paths, and `row_mode` is threaded through `_executeRawQuery`.',
    )
elif PR == '2282':
    body = must_replace(body, 'plus a docs page and one lockfile line', 'plus the app README (its user guide) and one lockfile line')
    body = must_replace(
        body,
        'new docs page `guides/apps/sql-explorer`.',
        f'user guide at `apps/sql-ui/README.md` (moved there from the docs site in `{SHORT}` per the app-docs rule that landed on develop in #2289).',
    )
    body = must_replace(body, 'Risks and limitations (documented in the docs page)', 'Risks and limitations (documented in the app README)')
else:
    raise SystemExit('unknown PR')

gh('PATCH', f'repos/{REPO}/pulls/{PR}', {'body': body})
with open(os.path.join(HERE, 'published-r2.md'), 'a') as log:
    log.write(f'- #{PR} description updated in place for {SHORT}\n')
print(f'description of #{PR} updated')
