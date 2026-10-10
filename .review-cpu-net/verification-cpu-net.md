# Independent verification — CPU pair (#1708/#2003) + IPv4 port (#2005)

Verifier: independent-verifier · 2026-09-09 (gh server time 2026-09-08T20:49Z at final check)
(Location note: the lead dir `…/pensive-kowalevski-be7b32/.review-cpu-net/` is write-protected for worktree-isolated agents — same restriction the primaries hit; delivered at the same relative path in the verifier worktree `…/agent-a357ccaad43d10cc7/.review-cpu-net/`.)
Stance: adversarial toward the two primary reviews; every ruling below is from my own re-derivation or precise code-path proof, not trust.

Pins re-confirmed at start AND end via gh: #1708 `1bf77b153b046a265220409b83b8a098b9cafbf6` (OPEN, CHANGES_REQUESTED) · #2003 `880f743f95869a959d557da71f79f60e83a0d68f` (OPEN, REVIEW_REQUIRED) · #2005 `e8379b596f4bf21d17a059c927dc133dd6c96a86` (OPEN, CHANGES_REQUESTED) · develop `9a5fc5c8`. **Zero head drift during verification.**
Merge-bases re-derived: 1708→`148379489c86`, 2003→`4a72f8d142d9`, 2005→`4a72f8d142d9`; depends.py blob at both CPU merge-bases = `e64fff95` (byte-identical), torch pin file byte-identical at both merge-bases and develop. All as the primary stated.

My environment: own isolated worktree (`agent-a357ccaad43d10cc7`, detached at the 2005 head for test runs; restored clean). uv **0.11.25** installed fresh into a scratchpad venv — I confirmed the repo pin myself: `_BOOTSTRAP_TOOL_VERSIONS['uv'] == '0.11.25'` at develop (depends.py:80) AND at both PR heads (line 69); CI lock lane 0.5.29 (lock-node-deps.yml:95) untouched by either PR. Python 3.14.3; pytest 9.1.1 / fastapi 0.141.1 / uvicorn 0.52.4 / websockets 17.1 (+ `requests`, which the real `ai.account` chain needs — the one env addition beyond the primary's list). Resolver-level only throughout; no torch/CUDA wheels downloaded; no CPU flags set anywhere persistent (fixtures constructed directly; env flags only inside short-lived probe processes). Full execution log at the end.

## Rulings per priority target

### T1 · #1708 P0 "flag is a no-op for the 6.6 GB" — **ACCEPT** (re-derived independently)
Replayed the PR's exact CPU-mode combine output (byte shape validated against the real imported `_combine_requirements` at head — probe) over the real `ai/common/torch/requirements.txt` (verbatim from `9a5fc5c8`, hash-equal at the PR's own merge-base), uv 0.11.25, `--python-version 3.12 --python-platform x86_64-manylinux_2_28 --index-strategy unsafe-best-match --no-build-isolation --emit-index-url`:
- **V1 (flag off) and V2 (flag on): sorted pin sets byte-identical** — sha1 `17572869c155` both: `torch==2.10.0+cu128`, `torchvision==0.25.0+cu128`, `triton==3.6.0`, **15 nvidia-\***, 31 pins.
- **V2 exits 0** — green, silent no-op; only the emitted index list differs (`whl/cpu` line added, unused).
- V5 (same + anonymize/gliner, 61 pins): still `+cu128`, 15 nvidia — robust with a real node in the set.
- Supporting: the PR's cited numbers (119/13→105/0; torch **2.6.0** in the matching issue-comment run) prove its verification omitted the pin file — 2.6.0 ≠ the pinned 2.10.0 — AND that run pinned `+cpu` manually, an override-style step the PR mechanism never performs. The primary's account is, if anything, understated.

### T2 · #1708 "standing CHANGES_REQUESTED is stale" — **ACCEPT, exact as phrased in the comment-input**
API: the only human review = asclearuc, CHANGES_REQUESTED, `submitted_at 2026-08-05T21:29:15Z`, **`commit_id = ae0b3f0ac363b894e8654fd29645761ab99dd28e`** — the FIRST commit. Head `1bf77b15` committed 2026-08-08T04:06Z, after the review.
- Blocking point 1 (cache key) **genuinely fixed at head**: `hasher.update(f'cpu_only={_cpu_only()}\n')` at depends.py:673; probe on the real function: `1/true/yes/' 1 '` one hash class, `unset/0/garbage` another, classes differ → exactly two classes, rebuild on both transitions.
- `_compute_hash` at `ae0b3f0` read directly: **no seed** → CodeRabbit's "Addressed in commit ae0b3f0" auto-marker was a false positive, exactly as asclearuc wrote in the review text.
- Point 2 (testability + tests) still unaddressed: `from engLib import ...` at line 52 of the head blob; diff touches only depends.py, no tests. The comment-input already scopes "stale" to point 1 and says point 2 remains — no correction needed.
- Thread states (GraphQL): the line-723 cache-key Major threads are resolved; the line-839 Darwin-docstring Minor is **unresolved and not outdated** — matches the report.

### T3 · #1708 ONNX/anonymize — **ACCEPT**
- Requirement lines verified in-tree at `9a5fc5c8`: anonymize = bare `gliner` + `onnxruntime-gpu==1.22.0; platform_system != 'Darwin'` + `onnxruntime==1.22.0; platform_system == 'Darwin'` (plain-ORT line Darwin-marked, inactive on Linux); the "all these files must agree" version policy is literally written in the file. (At 1708's own merge-base the pins were 1.20.1 — the 1.22.0 facts are current-tree, which is what F3 claims; drift correctly classified by the primary.)
- gliner: unpinned → resolves 0.2.29; **PyPI metadata: `onnxruntime` only behind the `onnx` extra, `onnxruntime-gpu` only behind `gpu`** — base gliner requires no ORT. Also visible in the resolution graph (V6 has no plain ORT).
- Dry-run replays (uv 0.11.25, linux/cp312, `--excludes`): base excludes (`uv`,`onnxruntime`) → **60 pkgs incl. `onnxruntime-gpu==1.22.0`**; 1708-CPU excludes (`uv`,`onnxruntime-gpu`) → **55 pkgs, zero ORT of either kind**, exit 0 both — `--excludes` silently drops even the direct requirement. Numbers match the primary exactly.
- audio_transcribe in CPU mode: `onnxruntime==1.29.0` via faster-whisper — plain ORT present but **floating past the coordinated 1.22.0** → the version-policy-break claim is confirmed too.
- Darwin excludes wart: code path at head 834–839 — on Darwin with flag set, the `elif _cpu_only()` branch fires and excludes `onnxruntime-gpu` contra the non-Darwin docstring → CodeRabbit's open Minor reproduces (thread confirmed open).

### T4 · #2003 Linux success — **ACCEPT**, and the override file is proven to be the operative mechanism
- V3 (pin file + CPU index + `--override` file): `torch==2.10.0+cpu`, `torchvision==0.25.0+cpu`, **0 nvidia**, no triton, 31→13 pins. V6 (+ anonymize/gliner): +cpu pair, **0 nvidia**, 43 pins, gliner 0.2.29, `onnxruntime-gpu==1.22.0` still present (ONNX deliberately out of scope — confirmed).
- **V3b (index only, no override): pin set identical to baseline** (+cu128, 15 nvidia) — the extra index alone does nothing against the pins; the override file does all the work. This also independently re-proves why #2003's first commit (= #1708's mechanism) was dead.
- Override content validated via the REAL imported `_torch_cpu_overrides_file` on a fixture exe-dir: exactly `torch==2.10.0+cpu\ntorchvision==0.25.0+cpu\n`, marker-less. Parity: T6 replay — a dry-run install with ONLY `-c <compiled constraints>` (no CLI index) resolves `+ torch==2.10.0+cu128`, i.e. uv 0.11.25 honors index lines inside `-c` files.

### T5 · #2003 P1 Darwin break + the marker-fix TRAP — **ACCEPT both**, safe to assert publicly
- V4 (darwin-arm64, flag semantics): **exit 1**, `torch==2.10.0+cpu has no wheels with a matching platform tag (e.g. macosx_13_0_arm64)`; hint lists linux/win platforms only. Control resolve (no flag): exit 0, plain 2.10.0/0.25.0.
- Import chain verified in code at head: `rocketlib/types.py:31` calls `depends()` at module import (line 29 imports, line 31 calls) → `ensure_constraints()` → flag value is in `_compute_hash` (raw seed, line 738) so flag-on always mismatches any stored hash → rebuild → `_compile_constraints` raises `RuntimeError('Failed to compile constraints')` (line 810) → propagates (no catch in `depends()`) → import fails → engine dependency bootstrap fails. No escape path: `_save_hash` runs only after a successful compile, so a flag-on hash can never be cached.
- **The trap (inverts CodeRabbit's public suggestion) re-proven**: V7b — marker-preserving overrides (`torch==2.10.0+cpu; platform_system != 'Darwin'`) on darwin → **exit 0 with a completely EMPTY resolve** (0 pins; torch AND torchvision silently gone — uv replaces the overridden requirement with the override, and a marker-false override replaces it with nothing). V7a: same overrides on linux → +cpu, 0 nvidia (fine). So the marker suggestion converts a loud Darwin failure into a silent no-torch resolve — worse. The "make the flag inert on Darwin" fix recommendation stands.
- CodeRabbit thread state: line-350 Major resolved (2nd commit addressed it); line-388 Major (the marker suggestion, posted 2026-08-18T22:54Z reviewing up to the current head) **open, not outdated** — review-current, as the primary said.

### T6 · Keeper logic — **ACCEPT** ("keep #2003, close #1708 after transfers" survives adversarial review)
- Premises all hold post-verification (T1: #1708 can't deliver; T4: #2003 does; T5: fixable, fix identified and trap avoided).
- **Full #1708 diff walked hunk-by-hunk** (+55/−2, one file): (1) `_compute_hash` seed + docstring, (2) `_cpu_only()` helper + opt-in rationale docstring, (3) `_combine_requirements` CPU-index injection + narrative comment, (4) `_write_excludes_file` flip + comments. The transfer list (a) excludes flip (b) normalized-bool seed + docstring (c) rationale prose covers ALL unique value; the only untransferred behavior is the index injection — the mechanism proven dead (V2), and #2003 provides the working index via CLI arg anyway. Nothing else exists in the diff.
- Flag names: `git grep` at `9a5fc5c8` — **zero hits for both** names anywhere in the tree (includes docs/, deploy/, helm, dockerfiles); GitHub org-wide code search — **0 results for both** (limited to repos visible to my token); PR search — each name appears only in its own PR. rocketride-saas: inaccessible to me too (GraphQL cannot resolve) — correctly recorded as **unavailable, not a pass**; the primary's keeper section carries this caveat and the comment-input sections do not assert the org-wide claim, so no public-comment exposure.
- Integration claims re-derived: merge-tree vs `9a5fc5c8` conflicts **only** in depends.py — #1708 exactly **1 hunk** (develop's `_excludes_content()` split vs the flip; mechanical), #2003 exactly **3 hunks**, and hunk 3 is the pure churn collision where develop's side contains the `_verdict_cached` check — a careless "take PR side" would delete it, verbatim as warned. Develop calls `_combine_requirements` twice (lines 812/815 — combined + overrides-combined) → #1708's in-function injection would stamp the header into the overrides file; T11 replay confirms uv parses AND honors `--extra-index-url` inside an override file (non-breaking, unintended channel — and the basis of the SaaS-overlay alternative, which is real). `_VERDICT_SCHEMA` bump policy is develop's own in-file comment ("Bump when the resolve's inputs or semantics change (uv arguments…)"). `constraints.lock` referenced only by the lock workflow + CHANGELOG, not by depends.py → "CI lint gate only" confirmed.
- Supporting numbers re-derived exactly: behind-counts 158 / 79 / 79; develop drift on depends.py +245/−7; #2003 churn = 8 em-dash→hyphen edits incl. the user-visible `'Waiting — {detail}'` status string.
- #2003 hygiene facts: **CI never ran at the head** — live check-runs API for `880f743f`: total_count=4 (Auto-label ×2, discord-notify ×2; no CI workflow, no Ruff, no build). Head blob passes ruff check + format --check under the repo pyproject at **0.16.5 — CI's actual pinned version at develop** (stronger than the primary's 0.14.4 run; both clean). F4 (raw hash seed → 4 distinct enabled-spelling hashes, `0` ≠ unset) and F5 edge-pin shapes (post-release/wildcard/range/commented → silently no override; case-insensitive and whitespace forms → matched) reproduced via the real functions.

### T7 · #2005 blocking finding — **ACCEPT** (CHANGES REQUIRED verdict stands)
- API: exactly one review — joshuadarron, CHANGES_REQUESTED, 2026-08-18T18:40:01Z, **`commit_id = e8379b596f4bf21d17a059c927dc133dd6c96a86` = the current head**. Current, not stale — in the strongest possible sense.
- The two offered resolutions are verbatim in the review body ((a) `get_local_uri()` + record family + 4 caller edits; (b) `Fixes`→`Refs` + honest scoping). Neither present at head: no `get_local_uri`/`_port_family` anywhere in src; body still opens `Fixes #994` (fresh fetch); **zero author replies** (PR comments = Discord bot + CodeRabbit only; reviewThreads totalCount = 0).
- Tests re-run myself (isolated venv, worktree detached at head, preload plugin replicating CI collection order — the conftest:24 `ai.account` collision is real and pre-existing; I hit it and worked around it the same way): **16 passed** full module; **3/3** focused `TestGetPort`, 0 skipped (IPv6 loopback bindable). Baseline both-files-at-merge-base: **13 passed**; delta = exactly the 3 new tests.
- **Discriminator**: merge-base `server.py` + head tests → `test_dual_stack_prefers_ipv4` **FAILS** (got the IPv6 port, expected IPv4; 1 failed 2 passed) — the test detects the old bug via family preference, not list position.
- **Connectivity mechanism re-reproduced from my own script**: real IPv4-only listener on P, `[::1]:P` verified actively refusing, `asyncio.open_connection('localhost', P)` under an IPv6-first resolver → `attempt ('::1', P, 0, 0) -> refused(61)` then `attempt ('127.0.0.1', P) -> ok` — exactly two attempts, wrong family first. And this host's **natural** `getaddrinfo('localhost')` order is `['IPv6','IPv4']` → not a Windows quirk, confirming the report.
- Caller audit at head: **exactly four** `f'http://localhost:{port}'` builders — task_cancel.py:28, task_status.py:31, task_data.py:516, task_exec.py:69 (get_port() calls at 24/27/512/65; the two other "localhost" hits in task_data are docstring curl examples, not callers).
- Implementation claims verified against the diff: OSError→continue and the tuple guard are unchanged pre-existing context; `_set_port` preserves the old condition + f-string; +25/−6 / +104/−0. F3 (both binds before `try`, `_bind_ipv6` closes only its own socket), F4 (no comment on the delenv teardown), the distinct-port skip, IPv6-listed-first stub, docstring prose at L803-805 vs Example block L810-812 — all line-exact at head. CI at head green (CI OK 2026-09-03 incl. Ruff + 3-platform builds), CodeRabbit "no actionable", `MERGEABLE`/`BLOCKED`, merge-tree onto `9a5fc5c8` clean (exit 0) — all re-confirmed.

### T8 · Comment-input audits — **all facts verified; no material drift**
Every SHA-pinned file:line in both Comment-input sections was checked against the head blobs; every number was re-derived (pin counts, nvidia counts, package counts, versions, dates, commit ids, behind-counts, conflict-hunk counts). Findings:
- **No false facts.** Nothing in either Comment-input section needs replacement.
- Refinements available to the comment writer (upgrades, not corrections):
  1. (#2003 fact 5) may now say: the head blob passes ruff check + format under the repo config at **ruff 0.16.5, the version CI pins at develop** (ci.yml:220, pinned per #1876) — removing the primary's "not CI's exact version" caveat.
  2. (#2005 fact 2) if line numbers are quoted for the URI strings themselves: the f-strings sit at task_cancel.py:28, task_status.py:31, **task_data.py:516**, **task_exec.py:69** (L512/L65 are the `get_port()` lines — same call sites, the review's own convention; both citations defensible, but 516/69 are the literal `http://localhost` lines).
  3. (#1708 fact 2) may add: the PR's cited verification not only omitted the pin file — it also **manually pinned `+cpu`** (per the matching issue-comment run), an override-style step the PR's own mechanism never performs.
- Evidence-level audit: the primaries claim resolver-level (2) or below for ALL CPU evidence and say so up front ("No level-4/5 evidence exists anywhere"); G additivity is labeled level-3-with-proxy-packages; ORT-gpu CPU-EP fallback labeled assumed. **No overreach found** — nothing is presented above the level its log supports. #2005's full-suite 1557→1560 figure is correctly labeled unverifiable (engine-bound); module-level 13→16 stands re-verified.

### T9 · Sweep — clean
- Execution claims without a logged command: none found that failed re-derivation; the two numbers stated outside the validation log (behind-counts, develop drift) re-derive exactly (158/79; +245/−7).
- "Introduced" without baseline: none — F1/F2/F4/F5 introduced-by-PR (correct; the features are the PRs), F3 "partly" with the gliner/ORT drift correctly attributed (I confirmed the 1.20.1→1.22.0 requirements change between 1708's merge-base and develop), F7 explicitly pre-existing (metadata-only hashing confirmed in all four blob states), 2005-F1 closure-claim-introduced/symptom-pre-existing correct.
- CI attribution: #1708 head CI green 2026-08-08 (checks started minutes after the head push — right commit); #2003 no CI at either commit (live-verified); #2005 CI OK 2026-09-03 at the head SHA. No misattribution.
- Reviewer edits to PR implementation code: **none.** The CPU reviewer's worktree depends.py hashes to the untouched user-branch state (`7c4fe503`); the 2005 reviewer's server.py/test_server.py are byte-identical to the PR head. Lead-dir report copies are byte-identical to the reviewers' originals.

## Decision log (disagreements / judgment calls)
1. **F1's P0 label**: I probed whether "P0" overstates an opt-in feature that regresses nothing when off. Kept ACCEPT: within this review's framing the flag's entire deliverable silently fails while reporting success — the highest severity *for the PR's purpose*, and it is the decisive keeper input, not a production-incident claim. The public one-liner already says "wrong delivery mechanism"; no wording change needed.
2. **"Stale review" phrasing** (#1708): "stale" is only true of blocking point 1; point 2 stands. The comment-input already splits them precisely — publish as written, and avoid a bare "the CHANGES_REQUESTED is stale" summary line anywhere else.
3. **"Nothing can depend on either flag in prod"** (matrix row): mild inference stacked on an unavailable check (saas repo). Confined to the internal report and properly caveated; keep it out of public comments (it already is).
4. **My probe design vs theirs** (#2005 connectivity): I verified `[::1]` refusal by active probe before the experiment rather than re-rolling on non-refusal; same self-validating property, same result — their design is sound.

## Validation-audit of the primaries (method integrity)
- Levels labeled consistently; the load-bearing checks (T2/T3, T4, T6, T7, T12b) all re-ran and matched, several to the digit (15 nvidia, 31/13/43/60/55 counts, `2.14.0+cpu`, `refused(61)`, empty V7b resolve).
- Disclosed stubs check out: engLib no-op stubbing is forced by `from engLib import ...` at :52 (both blobs); the ai.account preload matches how CI ordering masks the pre-existing conftest collision (chain read: `ai/account/__init__.py` calls `depends()` at import; store.py itself is stdlib-only at top level).
- Unavailable-not-pass discipline held: engine-bound suite, level 3–5 CPU evidence, saas repo, ORT CPU-EP fallback — all recorded as gaps, none as passes. One gap the primaries flagged (CI's exact ruff version) I was able to close: it is 0.16.5 at develop, and the #2003 blob is clean under it.

## Verdict deltas
**None. All four stand:**
- #2005 **CHANGES REQUIRED** — stands (review current at head via API; neither resolution present; the code itself verified sound).
- Keeper = **#2003 (rebased), close #1708 after transfers** — stands (P0 confirmed; V3b proves #1708's mechanism cannot be salvaged by the index alone; transfer list is complete against the full diff).
- #1708 **P0 no-op** — stands, re-derived from scratch with the repo-pinned uv.
- #2003 **P1 Darwin break** — stands, incl. the anti-fix warning (marker-preserving override silently deletes torch on Darwin — V7b, empty resolve, exit 0).

## Corrected comment facts
**No corrections required** — every fact in both Comment-input sections survived verification. Three optional refinements listed under T8 (ruff 0.16.5 upgrade; task_data.py:516 / task_exec.py:69 for the literal URI lines; the manual `+cpu` pin in #1708's cited evidence).

## Limits of this verification
- Same platform limits as the primaries: resolver-level only for all CPU claims (no install/import/functional run of torch+cpu — #1697's functional gate on the four nodes remains open and outranks everything); Windows resolver behavior taken from the review's on-platform evidence with the mechanism reproduced here; engine not buildable, so the engine-bound suite and the 1557→1560 figure remain unverifiable; rocketride-saas unreachable (org code search sees only repos my token can see).
- Cross-resolves approximate the engine's in-situ compile (`--python-version 3.12 --python-platform …` instead of the embedded interpreter's `--python`); metadata semantics identical; disclosed also by the primaries.
- My module import of the head blobs stubbed engLib (no-op) and, for the override probe, `_get_executable_dir`/`engine_cache_dir` (fixture dirs) — same class of accommodation the primaries disclosed.
- One primary env note: reproducing the #2005 test runs additionally required `requests` (pulled in by the real `ai.account.report`); absent from the primary's recorded package list but irrelevant to any result.

## Execution log (mine)
All uv runs: uv 0.11.25 (scratchpad venv `uvenv`), host arm64 macOS (Darwin 25.5.0); cwd = scratchpad/verify; fixtures verbatim `git show` at `9a5fc5c8` (hash-checked vs merge-bases). All pytest runs: scratchpad venv `tvenv` (py3.14.3, pytest 9.1.1), cwd = my worktree at the stated SHA.

| # | Command (abbrev.) | State | Exit | Result |
|---|---|---|---|---|
| V1 | `uv pip compile combined_A_base.txt` linux/cp312, unsafe-best-match, emit-index | pin file @9a5fc5c8 | 0 | 31 pins, +cu128 pair, triton, 15 nvidia (sha1 17572869c155) |
| V2 | same over 1708-CPU combine (header + cpu index line) | #1708 semantics | 0 | pin set **identical** to V1; emitted indexes only delta |
| V3 | V1 + `--extra-index-url whl/cpu --override overrides_2003.txt` | #2003 semantics | 0 | +cpu pair, 0 nvidia, 13 pins |
| V3b | V1 + cpu index, **no override** | isolation | 0 | identical to V1 → override does the work |
| V4 | V3 args, darwin-arm64 | #2003 Darwin | 1 | "torch==2.10.0+cpu has no wheels with a matching platform tag"; control V4c exit 0 plain 2.10.0 |
| V5 | V2 + anonymize reqs | #1708 fuller | 0 | +cu128, triton, 15 nvidia, 61 pins |
| V6 | V3 + anonymize reqs | #2003 fuller | 0 | +cpu, 0 nvidia, 43 pins, gliner 0.2.29, onnxruntime-gpu 1.22.0 in |
| V7a/b | marker-carrying +cpu overrides, linux then darwin | trap check | 0/0 | linux +cpu OK; darwin **EMPTY resolve** (0 pins) |
| V8 | 1708-CPU combine, darwin | #1708 Darwin | 0 | plain 2.10.0/0.25.0 |
| T5 | bare `torch` + cpu index, linux | unpinned case | 0 | torch==2.14.0+cpu, 0 nvidia |
| T6 | `uv pip install --dry-run -r (torch==2.10.0+cu128) -c out_V1` (no CLI index) | parity | 0 | `+ torch==2.10.0+cu128` — index lines in `-c` honored |
| T7a/b | dry-run anonymize, excludes base vs 1708-CPU, linux/cp312 | ONNX | 0/0 | 60 pkgs w/ ORT-gpu 1.22.0 vs 55 pkgs zero ORT; gliner 0.2.29 both |
| T7c | dry-run audio_transcribe, 1708-CPU excludes | ONNX float | 0 | faster-whisper 1.2.1 + onnxruntime==1.29.0 (floats past 1.22.0) |
| T11 | compile bare torch, `--override` file carrying its own cpu index line, no CLI index | override channel | 0 | torch==2.10.0+cpu — uv honors index lines in override files |
| P | probe.py: real imported head blobs (engLib no-op stub; exe/cache dirs fixtured) — 41 checks | both heads | 0 | 41/41 PASS: flag classes, hash classes (1708 two, 2003 four+), byte purity, override content/edge shapes |
| G | uv pip install six then idna into one target | additivity | 0 | six survives — installs never remove |
| L | ruff **0.16.5** (CI's develop pin, ci.yml:220) check + format --check, repo pyproject, 2003 head blob | lint | 0/0 | clean both |
| PT1 | pytest test_server.py (head, preload plugin) | e8379b59 | 0 | **16 passed** |
| PT2 | pytest ::TestGetPort (head) | e8379b59 | 0 | 3 passed, 0 skipped |
| PT3 | pytest module, both files @ merge-base | 4a72f8d14 | 0 | 13 passed |
| PT4 | pytest ::TestGetPort, merge-base server.py + head tests | mixed | 1 | **1 failed** (dual-stack got IPv6 port), 2 passed; worktree restored clean after |
| C | connectivity_check.py (v4 listener, [::1] refusal pre-verified, IPv6-first gai) | — | 0 | `('::1',P)→refused(61)` then `('127.0.0.1',P)→ok`; natural gai order IPv6-first |
| gh | reviews/commit_id for 1708+2005; check-runs 880f743f (total 4, no CI); reviewThreads (1708: line-839 minor open, line-723 majors resolved; 2003: line-388 major open, line-350 resolved; 2005: 0 threads); PR bodies/createdAt; code+PR searches (0/0; own PRs only); saas unresolvable; head OIDs at start + end | live | 0 | as cited throughout |
| git | merge-bases; blob hashes (pin file, anonymize @ 3 states, depends @ 4 states); merge-trees (1708: 1 hunk @890; 2003: 3 hunks @345/834/1198; 2005: clean); behind-counts 158/79/79; drift +245/−7; torchaudio grep (0); env-name greps (0); `ae0b3f0` `_compute_hash` read (no seed); reviewer-worktree file hashes | @pins | 0 | as cited |
