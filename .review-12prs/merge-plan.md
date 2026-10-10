# Merge plan
Relationships (verified, not title-inferred): #2004≡#1895 duplicate (keeper #1895) · #1908↔#2025 textual conflict in client-typescript/package.json + exports-map semantics (verifier re-derived byte-identical conflict) · #2117↔merged-#2127 one-hunk behavioral conflict (only develop's hint line is at risk under hunk-level resolution) · #1866↔#2007 share mixins/execution.py (1866's side docs-only → trivial rebase for the later one) · #1874↔#1901-rebuilt share client.py constructor region (small, mechanical) · #1382 superseded by develop a00c1804 · #1002 fully independent (tests/ only).

Sequence:
1. NOW, parallel: #1895 (re-review + 3 transfers) · #1866 (one-clause fix) · #1002 (two-line fix). Independent of each other.
2. #2025 after its pack-shell one-liner + react-types dep (unblocks its own CI); then #2007 (rebases trivially over #1866; both consumer updates in-PR — re-run MCP/status suites after landing).
3. #2117 (rebase w/ hint preserved, budget recalibrated, matcher narrowed) · #1874 (loopback + platform liveness + 0600 + docs) — independent of each other.
4. #1901 rebuilt (5 commits, +108/2 files) after #1874 lands (client.py rebase), with the subclass-forwarding case addressed.
5. #1908 split: engine-side PR (rollback semantics + row_mode guard + e2e wired into CI) first; SDK adapter PR second, AFTER #2025 (exports map), ideally via ./drizzle subpath to avoid the 11.7k contract mint.
Closures: #2004 after transfers land in #1895 · #1382 now, with the ~15-line follow-up (sendFiles pipe-close leak at client.ts:1865-1867 + maxConcurrent docs) filed separately.
Hold: #2011 until maintainers answer whether production Cloud serves rrext_deploy (in-tree evidence says the guard's premise is wrong; the PR would then close).
Post-landing re-validation: #2007 consumers after #1866 · #1901 kwargs tests after #1874 · #1908-SDK tarball/exports after #2025. A conflict-free merge is not semantic proof — the listed re-validations are the required checks.
