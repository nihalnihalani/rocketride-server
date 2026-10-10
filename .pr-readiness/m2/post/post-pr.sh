#!/bin/zsh
# post-pr.sh <pr> <run_id> <body_file> — substitute __RUN__, reply in every thread payload, post the summary, PATCH the description.
set -u
PR=$1; RUN=$2; BODY=$3
D=/Users/nihalnihalani/Desktop/Github/rocketride-server/.claude/worktrees/pensive-kowalevski-be7b32/.pr-readiness/m2/post/$PR
REPO=rocketride-org/rocketride-server
LINK="[run ${RUN}](https://github.com/${REPO}/actions/runs/${RUN})"
LOG=$D/published.md
echo "# Published for #$PR at $(date -u +%FT%TZ) (CI run $RUN)" >> $LOG
for f in $D/reply-*.json; do
  root=$(basename $f .json | sed 's/reply-//')
  tmp=$(mktemp)
  python3 -c "import json,sys; d=json.load(open('$f')); d['body']=d['body'].replace('__RUN__', '$LINK'); json.dump(d, open('$tmp','w'), ensure_ascii=False)"
  out=$(gh api -X POST "repos/${REPO}/pulls/${PR}/comments/${root}/replies" --input $tmp --jq '"\(.id) \(.html_url)"' 2>&1)
  echo "- reply to $root -> $out" | tee -a $LOG
  rm -f $tmp
done
tmp=$(mktemp)
python3 -c "import json; b=open('$D/summary.md').read().replace('__RUN__', '$LINK'); json.dump({'body': b}, open('$tmp','w'), ensure_ascii=False)"
out=$(gh api -X POST "repos/${REPO}/issues/${PR}/comments" --input $tmp --jq '"\(.id) \(.html_url)"' 2>&1)
echo "- summary comment -> $out" | tee -a $LOG
rm -f $tmp
tmp=$(mktemp)
python3 -c "import json; b=open('$BODY').read().replace('{CI}', '$LINK'); json.dump({'body': b}, open('$tmp','w'), ensure_ascii=False)"
out=$(gh api -X PATCH "repos/${REPO}/pulls/${PR}" --input $tmp --jq '"description updated (\(.body|length) chars)"' 2>&1)
echo "- $out" | tee -a $LOG
rm -f $tmp
out=$(gh api -X POST "repos/${REPO}/pulls/${PR}/requested_reviewers" --input <(printf '{"reviewers":["asclearuc"]}') --jq '[.requested_reviewers[].login]|join(",")' 2>&1)
echo "- re-requested reviewers now: $out" | tee -a $LOG
