# Inventory — 12-PR production-readiness review
Repo: rocketride-org/rocketride-server (upstream) · fork origin: nihalnihalani/rocketride-server
Analysis timestamp (UTC): 2026-09-07T19:33:03Z
Target branch: develop @ `973cd9b45ead293dd22fb8f7036ef1a1b325ca6b`
PR heads fetched to local refs: `refs/review-12prs/<N>` (shared object store; all verified equal to the GitHub API headRefOid at capture time).
Full per-PR metadata: `inventory/<N>.json` · complete changed-file lists (paginated, count-verified): `inventory/<N>-files.txt`
CI columns read from statusCheckRollup at the head SHA shown — reviewers must attribute check runs to commits themselves before trusting them.

| PR | State | Author | Base | Head | Size | Merge-base | ahead/behind | Integrates w/ develop | CI @head | Review decision | Title |
|---|---|---|---|---|---|---|---|---|---|---|---|
| #2117 | OPEN | madhumitha-chandrasekaran-1 | develop | `e4d4a858c` | +131/-13 (3f, 1c) | b1b45b855 | 1/38 | CONFLICTS | 18 ok / 0 fail | REVIEW_REQUIRED | fix(client-python): retry pipe open() on transient connect-refused |
| #2025 | OPEN | nishant-k02 | develop | `d1f3add47` | +146/-12 (5f, 1c) | 1b3943231 | 1/56 | clean | 11 ok / 5 fail | REVIEW_REQUIRED | fix(client-typescript): build and publish the app-sdk subpath export |
| #2011 | OPEN | piyarkhatrizx | develop | `49716a0dc` | +142/-1 (2f, 2c) | 4a72f8d14 | 2/61 | clean | 14 ok / 2 fail | REVIEW_REQUIRED | fix: guard deploy API on RocketRide Cloud |
| #2007 | OPEN | tanishq-eradala | develop | `f96da1508` | +28/-38 (2f, 1c) | 4a72f8d14 | 1/61 | clean | 16 ok / 2 fail | REVIEW_REQUIRED | fix(client-python): get_task_status now validates into TASK_STATUS |
| #2004 | OPEN | sujeito-operator | develop | `0078e6413` | +591/-23 (7f, 4c) | 4a72f8d14 | 4/61 | clean | 16 ok / 2 fail | REVIEW_REQUIRED | fix(client-python): bound send_files() fan-out with max_concurrent |
| #1908 | OPEN | dylan-savage | develop | `060b52192` | +13638/-58 (25f, 30c) | 210c9c7f5 | 30/48 | clean | 16 ok / 0 fail | REVIEW_REQUIRED | feat(client-typescript): Drizzle ORM over pipes (Sequelize deprecated, |
| #1901 | OPEN | erichanwang | develop | `58990420b` | +91199/-5751 (609f, 96c) | 6034cd411 | 96/91 | clean | 16 ok / 2 fail | REVIEW_REQUIRED | fix(client-python): reject unknown constructor kwargs instead of silen |
| #1895 | OPEN | maruthisai25 | develop | `a75c20ef8` | +309/-26 (9f, 7c) | 0788b9c49 | 7/1 | clean | 20 ok / 0 fail | CHANGES_REQUESTED | fix(client-python): bound send_files() concurrency with max_concurrent |
| #1874 | OPEN | madhumitha-chandrasekaran-1 | develop | `d1417095a` | +636/-7 (8f, 2c) | cf023e2bc | 2/100 | clean | 18 ok / 0 fail | REVIEW_REQUIRED | fix(vscode,sdk): make the local engine's dynamic port discoverable out |
| #1866 | OPEN | madhumitha-chandrasekaran-1 | develop | `fc81bb06f` | +25/-8 (5f, 6c) | 44b5190fc | 6/101 | clean | 16 ok / 0 fail | CHANGES_REQUESTED | fix(sdk): correct pipelineTraceLevel docstrings -- no _trace field exi |
| #1382 | OPEN | anshvermadev | develop | `3bf793390` | +46/-20 (7f, 12c) | 37cd05571 | 12/186 | CONFLICTS | 10 ok / 5 fail | REVIEW_REQUIRED | fix(client-typescript): implement documented maxConcurrent for sendFil |
| #1002 | OPEN | aryaMehta26 | develop | `5b2d9aa86` | +37/-6 (3f, 2c) | 4a09a435d | 2/160 | clean | 11 ok / 4 fail | REVIEW_REQUIRED | fix: test(client-typescript) disconnect timeout guard should reject in |

Starting hypotheses to verify (from the assignment — all unconfirmed): #2117 needs rebase (CONFIRMED conflicting); #1382 needs rebase after node dir renames (CONFIRMED conflicting); #2004/#1895 duplicate pair; #1901 polluted 609 files (file count CONFIRMED, pollution cause NOT yet established — note merge-tree vs develop is CLEAN); #1908 +13.6k (CONFIRMED, 25 files, 30 commits).
