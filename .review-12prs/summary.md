# 12-PR production-readiness review — executive summary
Analyzed against develop @ 973cd9b4; heads pinned per inventory.md (re-verified unchanged by the independent verifier at completion). Full evidence: prs/<N>.md, verification.md (1080-line adversarial pass: ~34 ACCEPT / 9 DOWNGRADE / 2 REJECT / 0 unresolved; all 12 verdicts stand), duplicate-analysis-2004-1895.md, branch-recovery-1901.md.

| PR | State | Verdict | Max confirmed sev | Validation | Main remaining action | Dependency/overlap | Order |
|---|---|---|---|---|---|---|---|
| #1895 | OPEN, CHANGES_REQUESTED (stale) | **READY** | none | executed×2 (indep re-instrumented, merged-tree too) | refresh review; 3 one-line transfers from #2004 | dupe pair w/ #2004 (keeper) | 1 (now) |
| #1866 | OPEN, CHANGES_REQUESTED (current) | CHANGES REQUIRED | P2 (one false clause) | source-verified (docs-only proven) | fix "'none'" clause in 5 files | shares mixins/execution.py w/ #2007 | 1 (now) |
| #1002 | OPEN | CHANGES REQUIRED | P1 (suites fail to collect) | executed (real suites; 74→0 baselined) | Promise<never> + MIT header | none (test-only) | 1 (now) |
| #2025 | OPEN | CHANGES REQUIRED | P1 (pack-shell path, outside diff) | executed (tarball proof ×4 cells; CI attributed airtight) | 1-line pack-shell + react types dep + ESM note | package.json conflict w/ #1908 → must land BEFORE 1908-SDK | 2 |
| #2007 | OPEN | CHANGES REQUIRED | P1 ×2 (breaks MCP monitor + web endpoint) | executed (both breaks reproduced) | update 2 consumers in-PR + F401 | file overlap w/ #1866 (docs-only side) | 2 (after 1866) |
| #2117 | OPEN, CONFLICTING | CHANGES REQUIRED | P1 (budget mis-spec) | executed client-half (fake engine); engine-half inspected | rebase preserving develop's hint line; recalibrate budget; narrow matcher | behavioral conflict w/ merged #2127 (one hunk) | 3 |
| #1874 | OPEN | CHANGES REQUIRED | P1 ×2 (credential redirect — reproduced ×2; Windows kill probe — code-path proof) | executed reader-half; writer/Windows inspected | loopback constraint; platform-aware liveness; 0600; docs | shares client.py w/ #1901-rebuilt | 3 |
| #1901 | OPEN | REBUILD | P2 (subclass-forwarding regression) | executed (cherry-pick byte-identical; 19 tests) | recreate as 5 commits on develop; ruff format; handle forwarding case | shares client.py w/ #1874 | 4 (after 1874) |
| #1908 | OPEN | CHANGES REQUIRED + SPLIT | P1 ×2 (silent empty rows; phantom commit — executed on Postgres 16) | executed (fake transport; sqlite+Postgres) | split engine-first/SDK-second; fix both P1s; ./drizzle subpath option | package.json conflict w/ #2025; e2e never runs in CI | 5 (engine), 6 (SDK, after #2025) |
| #2004 | OPEN | CHANGES REQUIRED → CLOSE | P2 (fabricated-failure overwrite) | executed (instrumented; cross-suite) | transfer 3 one-liners to #1895, then close | dupe pair w/ #1895 | close |
| #1382 | OPEN, CONFLICTING | REDUNDANT → CLOSE | n/a | executed (ancestry + semantics) | close; file ~15-line follow-up (pipe-close leak + docs) | superseded by a00c1804 (#1716) | close |
| #2011 | OPEN | CHANGES REQUIRED (blocked on maintainer answer) | P1 (all 16 deploy methods raise under default URI) | executed (probe at head); live-Cloud question OPEN | maintainers confirm whether Cloud serves rrext_deploy; if yes → close; else gate on capabilities | none | hold |

GitHub merge gates are separate from these technical verdicts: every PR still needs approving review; #2117/#1382 are additionally conflicted; branch-protection details were not API-readable (404 without admin).
