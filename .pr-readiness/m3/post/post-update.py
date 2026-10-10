#!/usr/bin/env python3
"""post-update.py <pr> <sha> <run_id> <counts> <extra_key=value ...> — fill the PR's draft from drafts.md, post it, re-request asclearuc."""
import json, os, re, subprocess, sys, tempfile
REPO = 'rocketride-org/rocketride-server'
PR, SHA, RUN, COUNTS = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
extra = dict(a.split('=', 1) for a in sys.argv[5:])
HERE = os.path.dirname(os.path.abspath(__file__))
drafts = open(os.path.join(HERE, 'drafts.md')).read()
m = re.search(r'## #' + PR + r'\n(.*?)(?=\n## #|\Z)', drafts, re.S)
body = m.group(1).strip()
LINK = f'[run {RUN}](https://github.com/{REPO}/actions/runs/{RUN})'
body = body.replace('{SHA}', SHA[:8]).replace('{RUN}', LINK).replace('{COUNTS}', COUNTS)
for k, v in extra.items():
    body = body.replace('{' + k + '}', v)
left = re.findall(r'\{[A-Z]+\}', body)
if left:
    raise SystemExit(f'unfilled placeholders: {left}')
def gh(method, path, payload):
    tmp = tempfile.NamedTemporaryFile('w', delete=False, suffix='.json'); json.dump(payload, tmp, ensure_ascii=False); tmp.close()
    out = subprocess.run(['gh', 'api', '-X', method, path, '--input', tmp.name], capture_output=True, text=True); os.unlink(tmp.name)
    if out.returncode != 0: raise SystemExit(out.stderr)
    return json.loads(out.stdout)
c = gh('POST', f'repos/{REPO}/issues/{PR}/comments', {'body': body})
r = gh('POST', f'repos/{REPO}/pulls/{PR}/requested_reviewers', {'reviewers': ['asclearuc']})
with open(os.path.join(HERE, 'published.md'), 'a') as log:
    log.write(f"- #{PR} @ {SHA[:8]}: comment {c['id']} {c['html_url']}; re-requested: {[u['login'] for u in r.get('requested_reviewers', [])]}\n")
print(c['html_url'])
