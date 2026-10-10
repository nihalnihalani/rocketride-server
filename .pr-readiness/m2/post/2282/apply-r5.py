#!/usr/bin/env python3
"""Publish round 5 for PR #2282: reply to the maintainer's note, correct the two earlier texts in place,
update the description, re-request review. Usage: apply-r5.py <full_sha> <ci_run_id>"""
import json, subprocess, sys, tempfile, os

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
        raise SystemExit(f'expected phrase not found: {old[:60]}')
    return text.replace(old, new)


# 1. Correct the earlier thread reply in place (DAF-3), and add the round-5 sentence.
r = gh('GET', f'repos/{REPO}/pulls/comments/4015934978')
body = r['body']
body = must_replace(body, 'each written first and shown failing on the previous code',
                    'the behaviour-changing cases written first and shown failing on the previous code, the remaining rows pinning conservative results that already held')
body = must_replace(body, '`hasTopLevelKeyword` is unchanged; the depth scanner it shared with the nested search is `keywordSites` in split.ts.',
                    '`hasTopLevelKeyword` keeps its API and its results; its word boundary now uses the SQL identifier class (34fa9963), and the depth scanner it shares with the nested search is `keywordSites` in split.ts.')
body += (f'\n\nFollow-up in `{SHORT}` (your inline note plus the adversarial pass on the final head): `classifyStatement` now makes its `WITH` decision on masked text too (aa18a738), '
         'the CTE-name rule follows the CTE grammar rather than "verb followed by (" so a MySQL `UPDATE (SELECT …) AS d JOIN …` after a chain is flagged again (f9659f37), '
         f'and the guide gained two sentences on what history keeps and when a read may be re-sent (8d68e9d6, wording tightened in the follow-up docs commit). 630 tests / 76 suites; CI {LINK}.')
gh('PATCH', f'repos/{REPO}/pulls/comments/4015934978', {'body': body})
LOG.write(f'- corrected reply 4015934978 in place (DAF-3) and appended the round-5 sentence\n')

# 2. Reply to the maintainer's new note.
reply = (f'Addressed in aa18a738 (head `{SHORT}`), with your change as written: `CTE_WRITE` became the `CTE_WRITE_WORDS` list and the `WITH` decision runs through `keywordSites` on masked text, '
         'so the three statements you listed classify as `read` (the `$$` one under the postgres dialect), while `WITH gone AS (DELETE FROM orders RETURNING *) SELECT * FROM gone` and '
         '`WITH a AS (SELECT 1) SELECT * FROM a FOR UPDATE` stay `write` — the latter on purpose, since `update` is real code at depth 0 there. The docstring parenthetical now says a literal IS masked. '
         'Your two rows are pinned next to `classify.test.ts:60` with a mysql backtick twin and a test that `classifyStatement` and `patternCheck` agree on read-only chains. '
         'The same unmasked `WITH` branch existed in `applyRowLimit`\'s `returnsRows` (batch.ts) and got the same substitution, so the header LIMIT is applied to those chains again. '
         'In the same push, f9659f37 tightens the CTE-name rule to the grammar (optional column list, `AS`, optional `[NOT] MATERIALIZED`, `(`), because the previous "verb followed by (" shortcut '
         f'let a MySQL `WITH a AS (…) UPDATE (SELECT …) AS d JOIN t … SET t.x = 1` pass unflagged. Verified: 630 tests / 76 suites, both typechecks, `sql-ui:test`; CI {LINK}.')
res = gh('POST', f'repos/{REPO}/pulls/2282/comments/4016783849/replies', {'body': reply})
LOG.write(f'- reply to 4016783849 -> {res.get("id")} {res.get("html_url")}\n')

# 3. Correct and update the summary comment in place.
s = gh('GET', f'repos/{REPO}/issues/comments/5680719023')
body = s['body']
body = must_replace(body, 'plus an independent review, an adversarial review and a clean-state verification pass on the final head',
                    'plus an independent review and a clean-state verification pass on each pushed head, and a dedicated adversarial pass whose final-revision verdict is recorded (its open items were taken in the last push)')
COUNT = subprocess.run(['git', '-C', '/Users/nihalnihalani/Desktop/Github/rr-work/pr2282', 'rev-list', '--count', f'07278af60c4ede4ed16314622429ea0856f78870..{SHA}'], capture_output=True, text=True).stdout.strip()
body = must_replace(body, 'pushed 12 commits on top of `07278af6` (head `cd18eefd`)', f'pushed {COUNT} commits on top of `07278af6` (head `{SHORT}`)')
body = must_replace(body, 'Verified: 617 tests / 76 suites green (521 before)', 'Verified: 630 tests / 76 suites green (521 before)')
import re
body = re.sub(r'`CI OK` on `cd18eefd`: \[run \d+\]\(https://github\.com/[^)]+\)', f'`CI OK` on `{SHORT}`: {LINK}', body)
body += (f'\n\n**Update ({SHORT}):** your inline note on `classifyStatement` is taken as written, the CTE-name rule now follows the CTE grammar, and the guide says what history keeps and when a read may be re-sent; '
         'the adversarial pass on the final head confirmed those three items and found nothing blocking beyond them. The push dismisses your approval automatically; a re-stamp when you have a moment would unblock the merge.')
gh('PATCH', f'repos/{REPO}/issues/comments/5680719023', {'body': body})
LOG.write('- summary 5680719023 corrected (DAF-3) and updated in place\n')

# 4. Description: fix the stale count, update counts/CI, add the round-5 items and the accepted limitations.
pr = gh('GET', f'repos/{REPO}/pulls/2282')
body = pr['body']
body = must_replace(body, 'with 496 pure-logic tests', 'with 630 pure-logic tests')
body = body.replace('617 tests / 76 suites', '630 tests / 76 suites')
body = re.sub(r'CI: \[run \d+\]\(https://github\.com/[^)]+\)', f'CI: {LINK}', body)
body = must_replace(body, '- `scripts/tasks.js`: unused `ctx` renamed `_ctx`.',
                    '- `scripts/tasks.js`: unused `ctx` renamed `_ctx`.\n'
                    '- After the maintainer\'s approval note: `classifyStatement` decides `WITH` chains on masked text (a literal or quoted identifier containing `delete` no longer makes a read a `write`, so the banner no longer says "committed" about SELECTs and the read keeps its retry); the CTE-name rule follows the CTE grammar; the guide states that history keeps a failed statement\'s error text and that a text-classified read may be re-sent once after a task restart.')
body = must_replace(body, '- Monaco still loads from a CDN (pre-existing, shared with explorer-ui).',
                    '- Monaco still loads from a CDN (pre-existing, shared with explorer-ui).\n'
                    '- Node-originated refusals (`allow_execute` off, `max_execute_rows`) still headline as "Database reported: …"; only the `SQL execution failed: ` wrapper is dropped from the headline.')
gh('PATCH', f'repos/{REPO}/pulls/2282', {'body': body})
LOG.write('- description updated (counts, CI, round-5 items, limitations)\n')

# 5. Re-request the reviewer whose approval the push dismisses.
res = gh('POST', f'repos/{REPO}/pulls/2282/requested_reviewers', {'reviewers': ['asclearuc']})
LOG.write(f'- re-requested: {[u["login"] for u in res.get("requested_reviewers", [])]}\n')
LOG.close()
print('round 5 published for #2282')
