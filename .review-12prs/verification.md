# Independent verification — 12-PR production-readiness review

Verifier: independent-verifier · adversarial re-derivation of the four primaries' findings.
Mandate: attempt to **disprove** each blocking finding before it reaches the final report.
Target: develop pinned @ `973cd9b45ead293dd22fb8f7036ef1a1b325ca6b` · PR heads at `refs/review-12prs/<N>`.

> **File location.** The shared-checkout path
> `.../pensive-kowalevski-be7b32/.review-12prs/verification.md` was **not writable** — agent worktree
> isolation refuses writes to another checkout. Per the fallback rule this file lives at the same
> relative path in my own worktree:
> **`/Users/nihalnihalani/Desktop/Github/rocketride-server/.claude/worktrees/agent-a53a4f1010dce7509/.review-12prs/verification.md`**
> No session scratchpad `out/` directory exists, so there is no third copy. **@lead — copy from the
> path above**, the same way `tasks.md:10` records for the other teammates.

**Environment (mine, built fresh — the primaries' venv was not reused):** macOS darwin 25.5.0 arm64 ·
git 2.50.1 · Python **3.12.12** (`/opt/homebrew/bin/python3.12`) · venv `<scratchpad>/iv/venv` ·
pytest 9.1.1 · pytest-asyncio 1.4.0 · pytest-timeout 2.4.0 · ruff 0.16.6 · Node v25.2.1 · gh 2.89.0.
Trees extracted **read-only** with `git archive --format=tar` + `tar -xf` into `<scratchpad>/iv/x/`.
No PR implementation file was edited anywhere; no checkout other than my own worktree was touched; no
`git stash`; no GitHub writes. Every `gh` call was a read (`api …/reviews`, `api …/check-runs`,
`pr view`, `pr list`). Final hygiene: my worktree `git status --porcelain` empty, all 12 refs
unchanged, the shared report dir contains no file I added.

**Method per finding:** try to disprove → check whether guards/callers prevent the trigger → compare
BASELINE (develop or merge-base) to test the introduced/pre-existing classification → re-execute or
re-derive → rule **ACCEPT / DOWNGRADE / REJECT / UNRESOLVED**. Where execution was impossible I say so
and give a code-path proof instead. An unrunnable check is recorded as **unavailable**, never a pass.

**A methodology note that matters, stated up front.** My first run of #1895's suite reported
`10 failed, 6 passed` and my first ruff run reported `70 errors` / `6 files would be reformatted` —
apparently contradicting the primary's "16 passed / all checks passed". Both were **my** error: the
repo's config lives in the **root** `pyproject.toml` (`asyncio_mode = "auto"`, `line-length = 320`,
`quote-style = "single"`), and I had run from `packages/client-python`, so pytest never collected the
async tests and ruff fell back to its own defaults. After placing each ref's own root `pyproject.toml`
into the extraction, both results matched the primary exactly. I record it because it is precisely the
failure mode that manufactures a false "the reviewer was wrong".

---

## Ruling summary

| # | Target | Ruling |
|---|---|---|
| 1 | **#1874** credential-redirect P1 · Windows `os.kill` P1 · 0600 rule · `'MYAPIKEY'` | **ACCEPT** F1/F3/F4/F5/F6/F7/F10/F11 · **DOWNGRADE F2 P2→P3** |
| 2 | **#1895** — the only READY | **ACCEPT** — survives, and is strengthened |
| 3 | Duplicate verdict (keep #1895 / close #2004) | **ACCEPT** — every load-bearing fact re-derived |
| 4 | **#1901** replay conclusion | **ACCEPT** ×5 · 3 supporting-detail defects found |
| 5 | **#1908** both P1s | **ACCEPT** ×2 (+F2 upgraded from reasoned to **executed**) · **DOWNGRADE** ×2 |
| 6 | **#2025** tarball + CI attribution chain | **ACCEPT** ×3 · **DOWNGRADE** F5's impact evidence · F2's "introduced" label corrected |
| 7 | **#1382** REDUNDANT | **ACCEPT** · **DOWNGRADE** F3's regression test · **UPGRADE** F4 to HIGH |
| 8 | **#1002** | **ACCEPT** ×3 (baseline gap closed) |
| 9 | **#2117** retry arithmetic · #2127 conflict · substring P2 | **ACCEPT** ×1 · **DOWNGRADE** ×2 (2 of 3 take-theirs consequences **REJECT**; F3 cost over-stated ~6×) |
| 10 | **#2011** premise contradiction | **ACCEPT** ×4 · live-Cloud question correctly kept OPEN · F1 *heading* over-asserts |
| 11 | **#2007** consumer breaks | **ACCEPT** ×4 (9 sites exact; `Optional[dict]`; F401 red + baselined; field-drop demonstrated) |
| 12 | **#1866** second blocking review | **ACCEPT** ×2 — review is current, and the reviewers' reading of the contested clause is right |

---

## 1. #1874 — riskiest PR · primary verdict CHANGES REQUIRED · **verdict stands**

### F1 credential-redirect (P1) — **ACCEPT**, reproduced independently

My own repro (`<scratchpad>/iv/iv_repro_1874.py`), not theirs. It writes a **real** discovery file and
drives the **real** `read_connection_discovery()` + `RocketRideClient.__init__`; only
`connection_discovery_path()` is patched, so the user's real config dir is never read or written
(verified absent before **and** after the run).

```
cmd  : /private/tmp/iv/venv/bin/python iv_repro_1874.py <pr1874 src> PR1874-d1417095a
cwd  : <scratchpad>/iv · tree pr1874 @ d1417095a · exit 0

live local entry, no env          : uri='ws://localhost:54321/task/service'            apikey='MYAPIKEY'
remote uri in file, env APIKEY    : uri='wss://attacker.example.com:5565/task/service' apikey='sk-users-cloud-key'
remote uri + file apiKey, no env  : uri='wss://attacker.example.com:5565/task/service' apikey='FILEKEY'
dead pid                          : uri='wss://api.rocketride.ai/task/service'         apikey=None
pid 0 / pid -1 / pid true         : accepted, treated alive
pid 1.5 (float)                   : REJECTED -> cloud default
explicit uri / env URI / explicit auth : all correctly win
```

The headline reproduces exactly: **a file on disk redirects the user's own cloud credential to an
arbitrary remote host.** Code confirms no host validation — `_connection_discovery.py:115` checks only
`isinstance(uri, str) and uri and isinstance(pid, int)`; `client.py:213-214` adopts the URI, `:219-222`
adopts the key.

**Baselined.** develop has no `_connection_discovery.py` at all and resolves
`uri = self._env.get('ROCKETRIDE_URI', CONST_DEFAULT_WEB_CLOUD)` (`client.py:204`). Executed on
develop: `no env, no auth → cloud default, apikey=None`; `env APIKEY only → cloud default`.
**Introduced — confirmed.**

*Addition the primary did not record:* line 3 above. When the file supplies **both** a remote `uri` and
an `apiKey`, the client adopts the attacker's key as well — so the file controls the client's entire
connection identity, not just its target.

### F4 Windows `os.kill(pid, 0)` (P1) — **ACCEPT** by code-path proof (execution impossible; marked)

Not executable — this host is macOS. **Unavailable, not a pass.** Ruled on two independent legs:

1. **Documented CPython semantics.** Python's library reference for `os.kill` states that on Windows
   only `CTRL_C_EVENT` / `CTRL_BREAK_EVENT` are signals, and that *any other value for `sig` causes the
   process to be killed by the `TerminateProcess` API, with the exit code set to `sig`*. Signal `0` is
   "any other value". (The local build's C-level docstring is only *"Kill a process with a signal."*,
   so the reference — not the docstring — is the authority here.)
2. **Code-path proof that it is reachable unguarded.** `_is_process_alive` (`:79-94`) contains **no**
   `sys.platform` branch — the only `sys.platform` checks in the module are at `:66`/`:69`, inside
   `get_user_config_dir()`, a different function. Chain verified:
   `client.py:213 → read_connection_discovery() → :118 check_process_alive → _is_process_alive → os.kill(pid, 0)`.
   Trigger: `RocketRideClient()` with no `uri` and no `ROCKETRIDE_URI`.

**Both halves hold.** Signal 0 routes to `TerminateProcess`, *and* the `except OSError: return True`
fallback (`:89-92`) makes a missing PID read as *alive* on Windows, because `ProcessLookupError` is
POSIX-only. So even under the most charitable reading of the first leg, the promised stale-entry
protection does not exist on Windows. The TS contrast is real: `process.kill(pid, 0)` at
`engine-local.ts:231` is documented by Node as platform-independent.

### F2 file permissions — **DOWNGRADE P2 → P3.** The fact is right; the cited precedent is not.

Fact confirmed empirically (umask 022 on this host):

```
cmd : node -e "fs.writeFileSync(p,'…'); statSync(p).mode & 0o777"
      no-mode -> 644 ;  {encoding:'utf8', mode:0o600} -> 600
```

`engine-local.ts:450` passes no `mode`, so the file lands 0644. That stands.

**But the house-rule claim does not.** The report says *"The same codebase writes **credential-bearing**
files with `{ encoding: 'utf8', mode: 0o600 }`"*, citing `service-linux.ts:118,158` and
`service-mac.ts:100,137`. I read all four. They write `tmpPlist` (a launchd plist) and `tmpUnit` (a
systemd unit) into a temp dir immediately before `sudo cp` into `/Library/LaunchDaemons` /
`/etc/systemd`. Grepping `buildPlist`'s body for `apikey|password|token|secret|credential` returns
**no match (exit 1)**. Those files carry **no credential**; the 0600 is TOCTOU hardening on a temp file
staged for a *privileged install* — a different rationale entirely.

The severity also over-reads the payload: the only secret-shaped content is `apiKey: 'MYAPIKEY'`, the
**public, well-known local default** (`connection/connection.ts:273`), and 0644-vs-0600 only matters
against a *second local user with read access* — a strictly weaker precondition than F1's, which needs
*write* access. **P3.** The remediation (`mode: 0o600`) is still worth doing as defence-in-depth and for
the day that key stops being a constant, but it must be justified as *"this file influences where a
credential is sent"*, not as *"the repo already does this for credential files"* — because it does not.

### F3 hardcoded `'MYAPIKEY'` adoption — **ACCEPT**

Writer confirmed at `engine-local.ts:454` (`apiKey: 'MYAPIKEY'`), with the PR's own comment at
`:438-446` openly acknowledging it is hardcoded rather than plumbed through. Reader adoption reproduced
above. Baseline: develop leaves `_apikey = None`. **Introduced — confirmed.**

### F5 / F6 / F7 / F10 / F11 — **ACCEPT**

* **F5** — a running local engine beats the documented cloud default: reproduced; develop returns the
  cloud default under identical inputs. **Introduced.**
* **F6** — `ROCKETRIDE_URI=''` no longer raises: reproduced on **both** trees. develop →
  `ValueError: Invalid URI '': missing hostname`; PR → `wss://api.rocketride.ai/task/service`.
  **Introduced.**
* **F7** — pid validation: `0`, `-1` and JSON `true` all pass the gate (`isinstance(True, int)` is
  `True`), and `_is_process_alive(0)` / `(-1)` both return `True` on POSIX. **Scope correction:**
  `pid: 1.5` **is** correctly rejected by the Python reader (`isinstance(1.5, int)` is `False`). The
  float hole is **TypeScript-only** (`typeof pid !== 'number'` admits `1.5`). The finding stands; its
  Python half should not claim floats.
* **F10** — advertised vs bound address: confirmed, and the irony is sharper than reported. The comment
  at `engine-local.ts:150-155` explicitly says *"Bind an explicit address, never the name 'localhost'"*
  and explains the ::1/127.0.0.1 ephemeral-port hazard — then `:167` (`emitStatus`, pre-existing) and
  `:453` (the new discovery file) both advertise `http://localhost:${port}`. The PR newly exports that
  hazard to arbitrary third-party consumers.
* **F11** — no CI coverage for the TypeScript half: `apps/vscode/scripts/tasks.js` exposes no test
  action (chain is `copy-readme → build-webview → compile-typescript → bundle-extension → stage-files →
  package-vsix`); grep for `node --test` / `vscode:test` / `src/test` across `.github/workflows/`
  returns nothing; `apps/vscode/src/test/` holds **5** test files nothing executes. The "18/18 green"
  covers none of the TypeScript.

### Clean-verified independently

The cross-language path contract (the feature's single most breakable invariant) reproduces
byte-for-byte on this host:

```
PY_READER_PATH = /Users/<user>/Library/Application Support/RocketRide/engine/connection.json
TS_WRITER_PATH = /Users/<user>/Library/Application Support/RocketRide/engine/connection.json
```

My TS side mirrors the PR's real `config-migration.ts:56-58` + `connectionDiscovery.ts:73`, checked
against the source.

---

## 2. #1895 — the only READY · **ACCEPT. The verdict survives.**

This one had to survive me or the plan changes. It does, on independent evidence.

### Diff, independently inspected

`git diff --stat 973cd9b4...refs/review-12prs/1895` → **9 files, +309/−26** — matches. Core read in
full: `max_concurrent: int = 5`; validation at `data.py:566-568` (bool excluded explicitly) **before any
pipe opens**; `asyncio.Semaphore(max_concurrent)` at **`:737`**; `upload_bounded()` holding a permit for
the whole open/write/close cycle; `gather(..., return_exceptions=True)` retained at **`:750`**;
`file_size` initialised `0` at `:637`, captured once at `:644`, reused at `:712` replacing develop's
`os.path.getsize(...) if os.path.exists(...)` re-stat; rationale comment at `:698-703`.

### Peak concurrency — re-verified with MY OWN instrumentation

Harness written from scratch (`<scratchpad>/iv/iv_harness_1895.py`), taking **three independent**
concurrency measurements so a bug in one instrument cannot fake a passing bound: **M1** live-pipe
counter, **M2** an explicit enter/exit in-flight counter, **M3** concurrently-open file objects via a
wrapping `open()`; plus peak `len(asyncio.all_tasks())`. Only the transport pipe and `builtins.open`
are substituted — `asyncio.gather`, the semaphore and the loop are the PR's own code.

```
cmd : iv_harness_1895.py <tree> <label>     exit 0 on all three trees

DEVELOP-973cd9b4  n=40  lim5  M1=40  M2=40  M3=40  tasks=41   o/c=40/40   holes=[] order=True
DEVELOP-973cd9b4  n=120 lim5  M1=120 M2=120 M3=120 tasks=121  o/c=120/120 holes=[] order=True
DEVELOP-973cd9b4  n=8   lim1  M1=8   M2=8   M3=8   tasks=9
PR1895-a75c20ef8  n=40  lim5  M1=5   M2=5   M3=5   tasks=41   o/c=40/40   holes=[] order=True
PR1895-a75c20ef8  n=40  lim3  M1=3   M2=3   M3=3   tasks=41
PR1895-a75c20ef8  n=120 lim5  M1=5   M2=5   M3=5   tasks=121  o/c=120/120 holes=[] order=True
PR1895-a75c20ef8  n=8   lim1  M1=1   M2=1   M3=1   tasks=9
PR2004-0078e6413  n=40  lim5  M1=5   M2=5   M3=5   tasks=6
PR2004-0078e6413  n=120 lim5  M1=5   M2=5   M3=5   tasks=6

two concurrent send_files, limit 5 each -> combined peak: develop 40 · #1895 10 · #2004 10
invalid limits (0,-1,True,5.0,'5',None): develop = no such param · #1895 all ValueError · #2004 all ValueError
```

**The primaries' numbers reproduce exactly on all three trees, on three independent instruments.**
`limit=1` is genuinely serial (peak 1, not 2 — the semaphore is not off-by-one). Order preserved. No
`None` holes anywhere. F2 confirmed (task count `n+1` on #1895 vs `limit+1` on #2004). F5 confirmed
(the bound is per-call; two concurrent calls reach 10).

*Instrument note:* on the injected-write-failure case my M1/M2 read 5 where the primaries report peak 4.
That is my counter design, not a discrepancy — I decrement only on `close()`, and the failed pipe is
deliberately never closed, so it stays counted. M3 (the real fd proxy) reads 4, and `o/c = 12/11`
matches their figure exactly. The client-side bound holds at 4.

### The PR's own suite and the lint gate — **both reproduce**

```
cmd : python -m pytest tests/test_send_files_concurrency.py tests/test_cli_upload_args.py -q \
        -c <tree>/pyproject.toml
cwd : <tree>/packages/client-python (a75c20ef8)     exit 0 · 16 passed in 0.25s

cmd : ruff check  --config <tree>/pyproject.toml <6 changed .py files>  -> "All checks passed!"
cmd : ruff format --check --config <tree>/pyproject.toml <same 6>       -> "6 files already formatted"
```

### CI green — **attributed to the current head** (a gap the primary explicitly left open)

`prs/1895.md` §5 honestly states *"I did not attribute individual check runs to commits."* I did:

```
cmd : gh api repos/rocketride-org/rocketride-server/commits/a75c20ef817b8333f1ae30ab7c28c2a81fc888f7/check-runs --paginate
-> every check_run carries head_sha = a75c20ef8 ; 20 success, 0 failure, 4 skipped
```

**20 ok / 0 fail is genuine and belongs to the current head.** Gap closed.

### The nine CHANGES_REQUESTED items — verified individually at head

Review fetched read-only: id `4889908375`, **joshuadarron**, `CHANGES_REQUESTED`,
`2026-08-08T22:09:25Z`, submitted against commit **`e9f6e501f`** — a revision *before* the current head.
Current `reviewDecision` is still `CHANGES_REQUESTED`; `mergeable = MERGEABLE`; last activity is a
CodeRabbit comment on `a75c20ef8` (2026-09-04). All exactly as the primary states. I read the full
review body and checked each item against the head:

| # | Item | Verified at `a75c20ef8` |
|---|---|---|
| 1 (block) | cleanup `close()` commits a truncated file | **Fixed** — `:694-703`: the `except` handler contains **no** `pipe.close()`; the comment explains why the pipe is left open |
| 2 (block) | that close is unbounded inside a bounded pool | **Moot** — no cleanup close exists |
| 3 (block) | `gather()` lost `return_exceptions=True` | **Fixed** — present at `:750` |
| 4 (block) | agent doc still says the opposite | **Fixed** — develop `:1112-1113` (*"File uploads are parallelized (all files uploaded concurrently)"* / *"The server handles queuing and rate limiting automatically"*) → PR `:1113-1114` correct; `:336` and `:530-541` also updated |
| 5 | CLI has no escape hatch | **Fixed** — `--max-concurrent` at `cli/main.py:428-429`, `type=positive_int` (`:79`), forwarded at `upload.py:278` |
| 6 | `None` holes / `getsize` TOCTOU | **Fixed** — `file_size` captured once; measured `holes=[]` in every harness case |
| 7 | `upload_time` changed meaning | **Fixed** — `types/data.py:169`: develop *"Time taken for the upload operation in seconds"* → *"Seconds spent uploading this file, excluding any wait for a free slot"* |
| 8 | *"`asyncio.Semaphore` does this in four lines"* | **Complied** — `:737` |
| 9 | third verbatim copy of the cleanup idiom | **Moot** — removed with item 1 |

**All nine addressed. ACCEPT the reconciliation table** — it is the basis of the READY verdict and it
holds line by line.

### Evidence gap I hunted and closed — full-suite regression check

The primary ran only the two new test files. I ran the **whole** runnable `client-python` suite on all
three trees (excluding `test_cli_integration.py` and `RocketRideClient_test.py`, which need a live
server):

```
cwd: <tree>/packages/client-python · -c <tree>/pyproject.toml --timeout=60
DEVELOP  973cd9b4  -> 56 passed, 21 errors
PR1895   a75c20ef8 -> 72 passed, 21 errors     (= 56 + the 16 new tests; identical error set)
PR2004   0078e6413 -> 77 passed, 21 errors
```

The 21 errors are the server-backed `test_deploy.py` / `test_tool.py` cases and are **identical on
develop**, so they are the pinned environment, not a regression. **#1895 introduces no regression in
anything runnable here** — evidence the primary did not have, and it strengthens READY.

### The merged state, not just the head — an extra check nobody ran

A READY verdict is a claim about what lands on develop, so I tested the **merged** tree rather than the
PR head alone. `git merge-tree --write-tree 973cd9b4 refs/review-12prs/1895` → tree
`9b4cf41923ecf960a6612be3064a195a9db1d8f0`, extracted read-only and re-tested:

```
merged data.py retains: :491 max_concurrent: int = 5 · :737 asyncio.Semaphore · :750 return_exceptions=True

MERGED-dev+1895  n=40  lim5  M1=5 M2=5 M3=5  tasks=41  o/c=40/40  holes=[] order=True
MERGED-dev+1895  n=120 lim5  M1=5 M2=5 M3=5  tasks=121 o/c=120/120 holes=[] order=True
MERGED-dev+1895  n=8   lim1  M1=1 M2=1 M3=1
two concurrent calls -> 10 · invalid limits -> all ValueError
full suite  -> 72 passed, 21 errors      (identical to the PR head and to develop's error set)
```

**The bound, the ordering, the hole-freedom and the suite all survive the merge unchanged.**

### Verdict

**READY stands**, contingent — as the primary says — on the standing `CHANGES_REQUESTED` being
dismissed or refreshed by joshuadarron. That is a process step, not code.

Residual nits confirmed, with **corrected line numbers** (the report's drift slightly, and the draft
comment would misdirect the author): `-> UPLOAD_RESULT` is at **`:492`** (report: `:491`);
`FileNotFoundError` in `Raises:` at **`:517`** (report: `:512`); the agent doc's `--pipeline` at `:159`
with the real flag at **`cli/main.py:413`** (report: `:402`).

---

## 3. Duplicate verdict (keep #1895 / close #2004) — **ACCEPT**

| Claim | My result |
|---|---|
| #1895 1 behind / 7 ahead; #2004 61 behind / 4 ahead | `rev-list --left-right --count` → `1 7` and `61 4` ✔ |
| both merge-tree clean vs develop | both exit 0 ✔ |
| #2004 CI red on `Ruff` → `CI OK` | `check-runs` at `0078e6413`: **2 failure = Ruff, CI OK**; 11 success, 4 skipped ✔ |
| #2004 has had no human review | `reviewDecision=REVIEW_REQUIRED`; non-bot reviews = **0** ✔ |
| #2004's ruff failure is its own, not staleness | `ruff format --check` on its 2 changed files → both would be reformatted, at `data.py:770` and `test_…:389` — **lines the PR added**. Staleness control: the *same* `data.py` at develop → *"1 file already formatted"* ✔ |
| cross-run: #2004's tests vs #1895 = 27 passed / 4 failed | reproduced **exactly**, same 4 test names ✔ |

### The single most load-bearing classification — re-derived from the test source

The analysis says only **two** of the four failures are real defects, and warns that reading all four as
defects **inverts the recommendation**. I read all four tests myself:

* `test_returns_one_result_per_file_in_the_annotation_too` — **REAL.** `-> UPLOAD_RESULT` at `:492`.
* `test_a_missing_file_raises_what_the_docstring_says` — **REAL.** Its operative line is
  `assert 'FileNotFoundError' not in raises`; `:517` still lists it.
* `test_a_file_that_vanishes_mid_upload_does_not_strand_the_queue` — **NOT a defect.** It patches
  `os.path.getsize` to raise on the *second* call for one file. #1895 has no second call (it reuses the
  captured `file_size`), so the fault never fires and the entry is `complete`. The test asserts
  `results[1]['action'] == 'error'` — i.e. **#2004's mitigation shape**. Reporting a genuinely-completed
  upload as `error` invites a duplicating retry; #1895's outcome is the correct one.
* `test_a_cancelled_worker_propagates_rather_than_returning_holes` — **NOT a defect.** It fails at
  `assert len(workers) == 3`, where `workers` are tasks whose coroutine is named `upload_worker`. #1895
  has none (its coroutine is `upload_bounded`), so the test aborts before reaching any behavioural
  assertion.

**Confirmed: exactly two are real. The recommendation does not invert.**

I pushed on the fourth anyway, because its docstring names a real concern, and measured the underlying
behaviour directly (`iv_childcancel.py` — cancel one `gather` child, not the caller):

```
DEVELOP    children=9 (upload_file)     -> send_files RETURNED, None_holes=[2]
PR-1895    children=9 (upload_bounded)  -> send_files RETURNED, None_holes=[3]
PR-2004    children=3 (upload_worker)   -> CancelledError PROPAGATED, no holes
```

The hole is **pre-existing on develop**; #1895 preserves it, #2004 genuinely fixes it. That does not
disturb "#1895 has no defects of its own" — it is develop's behaviour, and the analysis already lists
the fix as a #2004-only advantage (§7 item 5). One wording nit: §3's table marks develop *"n/a"* on that
row, which reads as "does not arise" when develop produces the identical hole; **"pre-existing"** is
accurate.

### #2004's own defect — reproduced independently, and genuinely #2004-only

My own probe (`iv_tailraise.py`) with the discriminator the coordination note warns about: fire **only**
on `upload_file`'s per-file line (contains `' bytes, '`), never on `send_files`' batch summary (contains
`' successful,'`). Both strings exist — per-file at `:728`/`:731`/`:715`, summary at `:790`/`:758`/`:734`
— so the warning is well founded, and my run confirms the summary line was reached without raising.

```
DEVELOP   actions=['complete']*4  bytes_sent=[64,64,64,64]  per_file_raises=4  summary_hits=1
PR-1895   actions=['complete']*4  bytes_sent=[64,64,64,64]  per_file_raises=4  summary_hits=1
PR-2004   actions=['error']*4     bytes_sent=[0,0,0,0]      per_file_raises=4  summary_hits=1
```

**Exact reproduction.** `upload_file` writes `results[index]` at `:722` then calls `debug_message()` at
`:728`; #2004's worker handler (`:753-764`) writes its `error` entry unconditionally, overwriting a
recorded success. It is a **regression against develop** (baselined) and does **not** exist in #1895.
One-line fix (`if results[index] is None:`).

### The three transfer one-liners — real and sufficient

1. `data.py:492` `-> UPLOAD_RESULT` → `-> List[UPLOAD_RESULT]`. **Feasible**: `List` already imported at
   `:59`. Closes cross-suite failure #1.
2. `data.py:517` delete `FileNotFoundError` from `Raises:`. The test's operative assertion is
   `'FileNotFoundError' not in raises`; its other assertions already pass on #1895 — so this edit alone
   closes failure #2.
3. `docs/agents/ROCKETRIDE_python_API.md:159` `--pipeline` → `--pipeline_path` (real flag at
   `cli/main.py:413`). Doc-only.

**Sufficient.** With 1 and 2 applied, all four cross-suite failures are accounted for.

**Recommendation stands: keep #1895, close #2004 with credit, file "bound pending work" as its own issue.**

---

## 4. #1901 replay conclusion — **ACCEPT** (all five sub-claims)

Re-derived in a **throwaway detached worktree created and removed for the purpose**; no other checkout
touched.

| Claim | Result |
|---|---|
| 5 author commits | `rev-list --cherry-pick --right-only --no-merges 973cd9b4...1901` → **exactly 5**, SHAs match 1:1. `--right-only` alone = 96; `--merges` = 0 (linear). 96 − 5 = 91 duplicates ✔ |
| two-dot = 2 files / +108 | `git diff --numstat 973cd9b4..1901` → `client.py` +47, `test_client_constructor_kwargs.py` +61 = **2 files, +108/−0** ✔. Three-dot = 609 files / +91199 / −5751 ✔. **The report's two-dot/three-dot labels are correct** (the assignment brief's parenthetical was the inverted one) |
| **cherry-pick → byte-identical tree** | **Three independent proofs.** (a) replay tree `be24a1f697440f2d00ecf32b526626f791a22e68` **==** PR head tree; (b) `git diff --stat 1901 <replay>` empty, exit 0; (c) `ls-tree -r` both = 4758 entries, identical SHA-256. All 5 cherry-picks applied with **zero conflicts** ✔ |
| forwarding-subclass regression | **Real and introduced.** Baselined: a subclass forwarding its own kwarg is ACCEPTED on develop, `TypeError` at PR head. Consume/pop forms unaffected ✔ |
| allowlist completeness (≥6 of 16 asked) | **All 16 checked.** Reconciliation: *in chain but not allowlisted* = `auth`, `uri` (signature params) and `transport` (deliberate); ***allowlisted but not in chain = none***. Docstring options and allowlist are identical sets ✔ |

**Nuance worth carrying:** develop's tolerance of the forwarding pattern is an artifact of a
*non-cooperative* base (`core/dap_base.py` never calls `super().__init__(**kwargs)`); in a standard
cooperative hierarchy the same pattern already raises. The PR therefore **restores** stock CPython
behaviour rather than breaking a blessed idiom. This softens the severity framing without changing the
introduced/pre-existing ruling.

**Three supporting-detail defects** (none overturns a ruling):

1. **§5-E's "none subclasses" is false.** `packages/ai/src/ai/common/models/base.py:269` —
   `class ModelClient(RocketRideClient):` — is an in-repo subclass at ~18 call sites. The *conclusion*
   survives: it calls `super().__init__(uri=…, module='MODEL_CLIENT', ws_path='/models')`, both
   allowlisted, executed as ACCEPTED on both trees. But "zero in-repo breakage" was reached without
   checking the one case that could have falsified it.
2. **Systematically wrong `client.py` line numbers** — develop's numbering used for the PR-head file.
   The check is at `:205-210` not `:191-196`; `super().__init__(...)` at **`:305`** not `:258`; the
   construction site at `:515` not `:468`. This propagates into the draft GitHub comment.
3. **8-vs-9 inconsistency** on newly documented options (measured: develop 8 → head 16, newly documented
   = **8**; §9/§6 say nine).

---

## 5. #1908 — both P1s · **ACCEPT ×2, with F2 upgraded from reasoned to executed**

| Claim | Ruling |
|---|---|
| **P1 #1 — `row_mode` absent → `[{}]` rows** | **ACCEPT.** Re-executed with an independent harness (fresh `drizzle-orm@0.45.2`, PR's two sources copied byte-identically — `shasum -a 256` verified — compiled with tsc 5.9.3, driven by my own stub): `[legacy] db.select().from(users) => [{}] | threw: undefined`. Silent, no throw. **Baseline the report never ran, now run:** the whole `drizzle` path is absent at develop *and* at merge-base, and `git grep rowMode` at develop exits 1. **Introduced — unassailable.** Premise is in fact *stronger* than argued: no JSON-schema validation exists anywhere in `packages/ai/src` at develop, so an old engine does not merely lack `additionalProperties: false` — it never validates tool input at all |
| **P1 #2 — begin→violation→commit on sqlite** | **ACCEPT.** Re-executed against both revisions: PR head → `commit() returned NORMALLY`, rows `[(1,'a'),(2,'b')]`; develop → `commit() RAISED KeyError`, rows `[(1,'a')]`. Tool-level translation confirmed at `db_instance_base.py:362`. **Introduced — confirmed.** *Correction to framing:* on **sqlite there is no data loss** — the pre-error write commits. The "silent discarded commit" shape is **Postgres-only**; §5 says so but the F2 bullet itself does not |
| **F2 Postgres reasoning** | **ACCEPT — and converted from reasoned to EXECUTED.** A throwaway `postgres:16-alpine` container (already present locally, `--rm`, loopback-only, since removed) settled it: PR head → `commit() RETURNED NORMALLY → client told {ok:true}`, but `id=2` **discarded**. Server log with `log_statement='all'` shows a literal `COMMIT` sent on an aborted transaction. The report's own open question ("if psycopg2 + SQLAlchemy raise `PendingRollbackError`, F2 degrades to P3") is **resolved against the degradation** — they do not raise. **F2 stays P1**, and the reasoning was a sound code-path proof with no gaps |
| **11,689-line decomposition** | **ACCEPT on every number** — `wc -l v2.d.ts` = **11689**; buckets 11,701 + 97 + 609 + 1,033 + 198 = **13,638** ✔; `diff v1 v2` = 138 added / 7 removed ✔. **DOWNGRADE one sentence:** *"v2 is a byte-copy of v1 plus `DrizzleDatabaseLike`, the three overloads, and JSDoc"* is **wrong** — hunk `11289a11389,11420` is **32 lines of unrelated develop drift** (pricing-card props), ~23 % of the semantic delta, swept in because v1 was minted 08-11 and v2 on 08-21. **New defect the report missed:** v2.d.ts's provenance header stamps `Source commit: 8cd38083…` (commit 29), but that tree does not contain the content baked into the file (the deprecation JSDoc is absent there, present at head) — the header records `git HEAD` at generation time, not the tree generated from, and the report cited it as provenance |
| **`shell:freeze --check` forces the mint** | **DOWNGRADE** — substance right, two precision errors. **(a)** CI runs **`shell:check`**, not `shell:freeze --check` (`ci.yml:277-281`, job *"Shell API contract"*); the two resolve to the same script mode, so this is terminological staleness. **(b)** `--check` **never mints** — `freeze-shell-api.js:829-847` exits 1 with *"Run `./builder shell:freeze`"*. So "forces" holds in the **blocking** sense, not the generating sense; the report's own prose ("fails without the v2 mint") is accurate. Mechanism verified exactly: `hasActionableChange` at `:515-524` compares only exported-name sets; `api.ts:184` is `export type * from 'rocketride';`; `DrizzleDatabaseLike` reaches the barrel via `client/index.ts:50` and is in v2 but not v1 → exit 1. **Unverifiable:** "a *required* CI job" in the branch-protection sense — `gh api …/branches/develop/protection` → **404** (no admin access). What *is* verified: it runs on any code-touching PR and exits nonzero on actionable drift |
| **#2025 package.json merge-tree conflict** | **ACCEPT.** `git merge-tree --write-tree refs/review-12prs/1908 refs/review-12prs/2025` → **exit 1, CONFLICT (content) in `packages/client-typescript/package.json`**, byte-identical to the reviewer's saved evidence (same tree oid, same three blob oids). The semantic half holds too: #2025 rewrites the analogous `"./analytics"` to `./dist/esm/client/analytics/index.js` while #1908 adds `"./drizzle"` un-nested |

**Two further report defects found:** F5's line citation is wrong (`is_escape_string` is at
`tx_registry.py:54`, not `:39`), and **F5's proposed regression-test criterion does not reproduce the
bug** — the stated case already passes at head (`binds={'b1': 1}`); the bug needs a backslash inside the
literal. A reviewer implementing it as written would ship a test that never fails.

---

## 6. #2025 — tarball proof and CI attribution chain · **ACCEPT ×3, DOWNGRADE ×1**

Rebuilt from scratch: `git archive` of `packages/client-typescript` at each SHA, `npm install
--ignore-scripts`, `tsc -p tsconfig.{cjs,esm,types,cli}.json`, hand-written `dist/{cjs,esm}/package.json`
module markers replicating `scripts/tasks.js:179-200`, `npm pack`, then install the `.tgz` into a plain
**non-workspace** consumer.

### Claim 1 — tarball proof, all four cells — **ACCEPT**

| cell | exit | result |
|---|---|---|
| baseline × CJS | **1** | `PASS rocketride` · `PASS analytics` · **`FAIL app-sdk :: MODULE_NOT_FOUND … dist/cjs/app-sdk/index.js`** |
| baseline × ESM | **1** | `PASS` · `PASS` · **`FAIL app-sdk :: ERR_MODULE_NOT_FOUND … dist/esm/app-sdk/index.js`** |
| PR × CJS | **0** | all three `PASS` |
| PR × ESM | **0** | all three `PASS` |

**Baseline really fails and the PR really passes, in both module systems.** Corroborated by an
independent artifact walker over `main`/`module`/`types`/every `exports[*]`/`bin`: baseline
`missing=3` (the three app-sdk entries), PR `missing=0`. The rootDir shift is confirmed *by building*,
not inferred: `dist/{cjs,esm,types}` each contain `app-sdk, client` at the PR head and no `app-sdk` at
baseline. **Caveat the report already discloses and I restate:** the app-sdk `PASS` is
*resolution-level* — the module loads with **0 runtime exports** (see Claim 4).

### Claim 2 — `pack-shell.js:179` hard-code as the cause of the 5 CI failures — **ACCEPT** (chain closes; attribution is *stronger* than the report claimed)

* **(a)** The hard-code exists verbatim at `pack-shell.js:179` and is byte-identical to develop's copy
  (`diff -q` exit 0). Repo-wide `git grep "'dist', 'types'"` at head returns exactly this one line.
* **(b)** `gh api …/commits/d1f3add4…/check-runs` → **exactly 5 failures**, no more:
  `Build / Ubuntu 22.04`, `Build / macOS (ARM64)`, `Build / Windows Server 2022`, `CI OK`,
  `check-externals (PR)`. Both runs carry `head_sha = d1f3add4…`, `run_attempt: 2`.
* **Attribution is airtight, better than stated.** Ubuntu log line 136:
  `HEAD is now at 19ccd53 Merge d1f3add4… into 1b3943231…`, and `git rev-parse d1f3add4^` =
  `1b3943231…` = the merge-base. Merging a commit into its own parent yields that commit's tree — CI
  tested **precisely the PR-head tree**.
* **(c)** Logs trace to the line. Ubuntu (1883 lines): the **only** `[FAILED]` lines are the pack-shell
  message, with `at packShell (…/pack-shell.js:179:79)`. macOS and Windows identical.
  `check-externals` (5588 lines): `grep -c FAILED` → **4**, all four the same message, zero others.
  `CI OK` is a pure aggregate (`build=failure`, everything else success/skipped).
* **Adversarial control for "stale base or flake":** develop @ `973cd9b4` *does* carry an independent
  `Build / Ubuntu 22.04` failure (run 33890564770), but its log is an unrelated apt/network flake
  (`apt.llvm.org … Network is unreachable`) — different root cause, no overlap.

Two cosmetic imprecisions, neither affecting the conclusion: `check-externals (PR)` belongs to run
**`32079322947`**, not `32079323156`; and the report's *"STARTED with no `[FAILED]`"* understates the
log, which shows the whole SDK chain **`[COMPLETED]`** before pack-shell failed.

### Claim 3 — react-types P2 (F3) — **ACCEPT**, and the baseline holds under attack

Every citation exact (`types.ts:35`, emitted `types.d.ts:1`, `index.d.ts:138`, root `package.json:46`
`"@types/react": "~18.3.31"` in devDependencies, no react of any kind in the package's own
`package.json`). Isolated build without react → `TS2503: Cannot find namespace 'React'` +
`TS2307: Cannot find module 'react'`, exit 2; after installing `@types/react`, all four configs exit 0
— confirming the report's discriminator that this is an environment artifact of the isolated install,
not a PR defect. Clean-consumer repro against the PR tarball reproduces both errors and they vanish
after installing `@types/react`, while the sequelize/`asyncDispose` diagnostics remain.

**The baseline is properly established** — this is the part most worth breaking, and it did not break:
`diff -q` on `src/app-sdk/{types,index}.ts` develop vs PR head → **exit 0** (the react import is
pre-existing in source), and the same probe against the *baseline* tarball produces
`TS2307: Cannot find module 'rocketride/app-sdk'` instead of the react errors. So *"newly reachable —
the import is pre-existing, this PR is what ships it"* is precisely right.

**A gap the report itself flagged, now closed:** it listed `stripDtsDir` as "not covered / skipped". Run
(`stripped files: 13`, exit 0): the React import survives, no `.d.ts` moves, re-pack still
`missing=0`. It *does* delete 13 stale `.d.ts.map` files — so "does not move files" is right, but
"does not remove files" would not have been.

### Claim 4 — empty-ESM `export {}` P2 (F5) — **DOWNGRADE.** Technical core verified; its stated trigger is misattributed.

The technical core is fully confirmed: `dist/esm/app-sdk/index.js`'s sole statement is `export {};`;
CJS exports nothing; `src/app-sdk/index.ts` has **13** `export declare`s matching the report's list
one-for-one; a static named import throws
`SyntaxError: The requested module 'rocketride/app-sdk' does not provide an export named
'connectionManager'`; namespace import gives `[]`; CJS gives `undefined` **silently**. Baseline is
loud (`ERR_MODULE_NOT_FOUND`), so "loud before, hollow after" holds.

**Why I downgrade:** the finding's stated evidence for user-facing impact is *"Docs at
`README-apps.md:125/146/165` show value-import forms"*. Those three lines are all **`import type`** —
erased at compile time, and therefore **incapable** of producing the runtime `SyntaxError` the finding
describes. The draft GitHub comment compounds it: it cites
*"the value imports shown in `docs/README-apps.md` (`import { connectionManager } …`)"*, but that
example is at line 643 and imports from **`'shell'`**, not from `rocketride/app-sdk`.

The hazard is nonetheless real — a genuine value-import-from-app-sdk form is documented, just in a
different file: `src/app-sdk/index.ts:30`. **Net: real defect, wrong evidence for its impact, and the
proposed docs fix lands in the wrong place as specified.**

### Additional audit finding for #2025

**F2's "introduced (latent)" label is wrong.** Its **Where** cites
`packages/ai/src/ai/modules/mcp/apps/tsconfig.json:15` as if present at the reviewed head, but
`git ls-tree -r d1f3add4 -- packages/ai/src/ai/modules/mcp/apps` returns **nothing** — that whole
subtree postdates the PR's branch point and exists only on develop. Correct classification:
*pre-existing config that this PR invalidates in the merged state*, not "introduced". The dormancy
claim itself checks out (nothing in that subtree imports `rocketride`), so impact stays P3. Contrast
F1, which explicitly and correctly states its file is *"present identically at the PR head and at
develop"* (confirmed, `diff -q` exit 0).

**No reviewer edits — positively disproven, not merely unobserved.** The reviewer's worktree sits at
`973cd9b4` **detached**; they never checked the PR out. Their saved artifacts are byte-identical to
git: the PR tarball's `package/package.json` vs the ref's → `diff` exit 0; the baseline tarball's vs
develop's → exit 0; `pack-shell-prhead.js` vs the ref → exit 0. Their `merged-2025.txt` tree oid
`1e90bd6d4…` reproduces my own independent `git merge-tree --write-tree 973cd9b4 d1f3add4`.

---

## 7. #1382 — REDUNDANT · **ACCEPT** (with one remediation defect)

| Claim | Ruling |
|---|---|
| `a00c1804` ancestry | **ACCEPT.** `git merge-base --is-ancestor a00c1804 973cd9b4` → **exit 0**. Commit is *"fix sendFiles maxConcurrent (#1716)"*, Eric Wang, 2026-08-07 — author, date and subject match verbatim |
| develop covers the PR's semantics | **ACCEPT**, by **runnable probe** (both `sendFiles()` bodies mechanically sliced from the real files, anchor-asserted, run under Node v25.2.1). Direction confirmed: **develop = fail-fast** (`client.ts:1772-1775` throws), **PR = coercion** (`client.ts:1479-1480`). It *does* matter to a caller: `maxConcurrent=0` → PR silently runs at 1; `NaN`/`Infinity` → PR silently runs at 5; develop rejects all of them. Everything else identical — empty input, peak bound at mc=1/3/5/100, ordering under mixed failure |
| the follow-up pipe leak | **ACCEPT, and UPGRADE to HIGH confidence.** Line-precise at develop: `sendFiles()` catch at `client.ts:1865-1867` **does not close**; `send()` catch at `:1714-1723` **does** (cleanup `:1716-1722`). Measured (3 files all failing mid-write): develop `opened=3 closed=0 STILL-OPEN=3`; PR `opened=3 closed=3 STILL-OPEN=0`. Pre-existing on develop, fixed by the PR. The report rated it MEDIUM-HIGH because it was static-only; it is now runtime-verified |

**DOWNGRADE — a defect in F3's remediation.** develop's guard sits inside an `async` function, so the
`RangeError` is a **rejection, not a synchronous throw**. The report's prescribed regression test
(`expect(() => client.sendFiles(files, token, 0)).toThrow(RangeError)`) was executed and **does not
catch** (`caught=false`), re-confirmed under jest-jasmine2. It must be
`await expect(...).rejects.toThrow(RangeError)` — as written it would silently pass against a broken
implementation.

**Two sub-claims to downgrade inside F4/F2:** F4's *"not returned to the **pool's accounting**"* reads
as client-side pool starvation, which is **false** (all 3 files processed with 2 workers despite 3
leaks) — defensible only as *server-side*, which is unverifiable here. F2's *"`debugMessage` hides
upload failures"* overstates reach: per-file failures never reach that log line on either side
(measured: 0 `debugMessage` calls during a normal per-file failure). **Citation nit:** F2 cites
`client.ts:1473-1474`, which are comment lines; the coercion is at `:1479-1480`.

**Verdict REDUNDANT: sustained.**

---

## 8. #1002 — **ACCEPT** ×3, with the report's one evidence gap closed

| Claim | Ruling |
|---|---|
| TS2322 repro, both suites fail to collect | **ACCEPT, strengthened.** tsc 5.9.3 / jest 29.7.0 (matching the report's environment): `tests/timeoutGuard.ts(24,3): error TS2322: Type 'void \| Awaited<T>' is not assignable to type 'T'` — verbatim, at 24:3, `TSC_EXIT=2`. I ran the **real** suites (the report used a synthetic probe): `Test Suites: 2 failed, 2 total · Tests: 0 total`, both citing `timeoutGuard.ts:24:3`. Failure is at transform time, so no live engine is needed |
| test-only scope | **ACCEPT.** `git diff --name-only 4a09a435d...refs/review-12prs/1002` → exactly 3 files, all under `tests/`. **Zero files under any `src/`** |
| the two disproofs | **ACCEPT both.** Probed against the PR's *unmodified* `timeoutGuard.ts` (copy verified byte-identical by `cksum`), then re-run under the repo's real jest-jasmine2 + ts-jest. (a) no unhandled rejection: `UNHANDLED REJECTIONS = 0` at 20 ms, 120 ms and 1000 ms; (b) timer cleared: `setTimeout=1 clearTimeout=1 liveTimersLeft=0`, and the **old** inline form measurably leaks (`clearTimeout=0, liveTimersLeft=1`). Both disproofs survive |

**Baseline gap the report never closed — I closed it.** The report asserted "introduced" for F1 without
running the merge-base. Same jest, same `node_modules`, at `4a09a435d`:
`Tests: 63 failed, 6 skipped, 5 passed, 74 total`, with `grep -c "Test suite failed to run"` → **0** and
`grep -c TS2322` → **0**. So **74 tests collect at merge-base → 0 at head.** The classification was
correct; the report's own evidence did not establish it.

*Nuance (not a refutation):* the exported-but-unused `makeTimeoutRejector`, used standalone without
racing or clearing, **does** produce an unhandled rejection. The disproof is correctly scoped to current
usage inside `withTimeoutGuard`, but it is not a property of the exported API — relevant to the report's
own open question 3.

**Verdict CHANGES REQUIRED: sustained.**

---

## 9. #2117 — **ACCEPT ×1, DOWNGRADE ×2**

### Claim 1 — develop's inner 10 × 150 ms retry and the "~4.8 s" arithmetic — **ACCEPT**

`task_engine.py:751-757` at develop confirms `stop_after_attempt(10)`, `wait_fixed(0.15)`, `reraise=True`,
guarded by `if not self._data_client:` at `:748`. The race comment sits at `:743-747`.

The arithmetic checks out, and a probe sharpens it: tenacity performs **9** sleeps for 10 attempts
(`attempts=10 before_sleep_calls=9 elapsed=1.359s`), so develop's exhausted loop is 9 × 0.15 =
**1.35 s**. `_data_client` is assigned only on success (`:769`), so each *client* attempt re-enters the
whole loop → 3 × 1.35 + the PR's own 0.25 + 0.50 backoff = **4.80 s**, ratio 3.56× ("~3.5×"). Nothing
truncates it: `dap_client.py:86` defaults `request_timeout` to `None`. `git log -S` confirms the loop
dates to the initial commit and is present at the merge-base. The report correctly labels 4.8 s as
**arithmetic, not measured**.

### Claim 2 — one-hunk conflict vs #2127 and the take-theirs trap — **DOWNGRADE**

**The conflict claim is ACCEPT and exact.** `git merge-tree --write-tree 973cd9b4 e4d4a858c` → exit 1,
tree `ccebfc42…`, with stage blobs `efe23ba8`/`067b924c`/`a98920f7` — every value matches the report.
`git merge-file` → exit 1 = **exactly one** conflict hunk at merged lines 200-220. #2127's merge commit
is `4e6e56cd58924459a699c46fe7670b87396fc9e0` (merged 2026-08-31), the only develop commit touching
`data.py` since the merge-base.

**But two of the three "take-theirs regression" consequences are REJECT** for the resolution actually
described (a hunk-level take-theirs). The conflict *tail* auto-merges, and that changes the outcome:

* **`hint` lost — ACCEPT.** develop's `response['hint'] = (…)` (`data.py:191`) does disappear.
* **"developer checklist leaks into end-user text" — REJECT.** The base's
  `response = dict(response); response['message'] = msg` (`:194-195`) was deleted one-sidedly by
  develop, so git drops those lines cleanly **outside** the conflict. `msg` is built and then
  **discarded**; `raise PipeException(response)` carries the raw server response. (`ruff check --select F`
  on the resolved file → exit 0, so CI would not flag the dead variable either.)
* **"`mimetype=` reintroduced" — REJECT.** develop's `mimetype=` → `mime_type=` fix is a one-sided
  change, so it **auto-merges and survives** at merged line 224, outside the markers.

Both rejected consequences hold only under a **whole-file** `git checkout --theirs`. The report should
say which resolution it means. Two further report errors here: §7's claim that *"`data_conn.py` and
`task_engine.py` are unchanged over the same range"* is **wrong for `task_engine.py`** — `4e6e56cd`
changed 3 lines (a `TaskError` import and two `RuntimeError` → `TaskError` raises); the retry block is
untouched, so F1's conclusion survives. And **F2 carries a "(reproduced)" tag** while its evidence (E5)
reproduced *PR-head* behaviour, not the merge outcome — which, per the above, materially differs.

### Claim 3 — P2 substring false positive — **DOWNGRADE**

The predicate is at `mixins/data.py:73-74` (**not `:71-72`** as cited):
`return 'Connect call failed' in message or 'Connection refused' in message`.

Measured against a freshly-closed port: the **target** hop (async `websockets.connect`) yields
`[Errno 61] Connect call failed …` → matches; the *non-target* paths — sync `websockets.sync.client`
(`IInstance.beginInstance`) and the `requests.post` stand-in (`IGlobal.py:73`) — yield
`[Errno 61] Connection refused` → **also match**. So the false positive is **real at predicate level**:
`'Connection refused'` matches only paths that are *not* the hop being retried.

Two downgrades: **(a)** the last hop is **unavailable, not passed** — `grep -rn beginInstance` finds
only the definition; it is invoked by the C++ engine-lib, which is not buildable here, so "a remote
node's refusal surfaces as the `open()` DAP message" is inspection-only. **(b)** the cost figure is
**mis-derived**: F3 says "retries 3× (≈4.8 s per F1)", but F1's 4.8 s assumes the engine's inner loop
re-runs per client attempt; in the remote-node path the data channel connects fine, `_data_client` is
already set, and `:748` is skipped — real cost ≈ the 0.75 s client backoff, **over-stated ~6×**.

---

## 10. #2011 — premise contradiction · **ACCEPT ×4, with one heading flagged**

| Claim | Ruling |
|---|---|
| in-tree server mixes `DeployCommands` unconditionally | **ACCEPT, exact.** `task_conn.py:77` import, `:108` in the class bases, `:199` `DeployCommands.__init__(self, connection_id, server, transport, **kwargs)`. `grep -n "edition\|is_saas\|oss"` over the file finds **no guard anywhere** |
| the `deployment_backend.py` / `base.py` quotes | **ACCEPT, verbatim.** `deployment_backend.py:23-25` (report says `:23-24`) and `base.py:462-465` — including *"callers (cmd_deploy, the scheduler, UIs) never branch on edition"* at `:465` |
| capabilities at `types/client.py:345-352` | **ACCEPT.** Chain real end-to-end: `account/base.py:55` `capabilities: tuple[str, ...] = ()` (report says `:53`) → `account/oss/__init__.py:66` `('oss',)` → server emits at `cmd_public.py:96` → SDK reads via `client.py:441 get_server_info()`. **What it actually does:** a one-way *edition advertisement*, not negotiation — a `TypedDict` with zero runtime validation, tagging edition rather than per-command features. Gating deploy on it yields the same bit as the hostname test, only server-sourced. The report does not oversell it |
| "`RocketRideClient(auth=…)` loses `client.deploy`" | **ACCEPT with a wording downgrade — EXECUTED.** Probe against `pr2011` @ `49716a0d`, exit 0: `hasattr(client,'deploy') → True`, `type → DeployApi`, uri `wss://api.rocketride.ai/task/service`; but `list`/`preview`/`get` each raise `RuntimeError: Deploy operations are not supported on RocketRide Cloud.` **16 public methods / 16 `_ensure_supported()` calls**, guard at `deploy.py:109-118`. So the namespace object is *not* lost — every method on it raises. "Loses `client.deploy` entirely" should be reworded; the practical effect is unchanged |

Also re-derived: the ruff red is genuine and **baselined** — PR `ruff format --check` exit 1
("2 files would be reformatted", trailing whitespace at `deploy.py:66`, `:116-118`), while develop's
`deploy.py` → exit 0. `pytest tests/test_deploy_unit.py` → **21 passed**. The host matrix reproduces
§5-C exactly (4 BLOCKED / 4 ALLOWED). `rrext_deploy_add`/`rrext_deploy_list` → zero hits repo-wide.

### Claim 8 — is the live-Cloud question kept OPEN? — **ACCEPT, no over-assertion**

The report states it as unresolved in **five** places, including §5 (*"cannot be determined from this
repo"*), §8 Q1 (*"**(blocking)** … **Needs a maintainer**"*), and the coordination note (*"that is
deliberately left as an open question, **not a finding**"*). It does **not** assert it.

**One flag:** F1's *heading* — "blocks a deploy API that **this repo's server implements on SaaS**" —
asserts more than the body supports. There is no `packages/ai/src/ai/account/saas` in-tree
(`ls` → No such file or directory); the SaaS override is out-of-tree and known only from the docstrings.
Heading over-reach, thoroughly hedged everywhere else.

---

## 11. #2007 — consumer breaks · **ACCEPT ×4**

| Claim | Ruling |
|---|---|
| `visibility.py` `.get()` sites, "9" | **ACCEPT, exact count = 9** — `:107, :111, :112, :122, :123, :124, :126, :127, :165`. Probe: develop `sites broken = 0/9`; PR head `9/9`, first failure `visibility.py:107 AttributeError: 'TASK_STATUS' object has no attribute 'get'`. Critically, `bool(TASK_STATUS instance) is True`, so the `or {}` at `:152` does **not** rescue it |
| `ResultSuccess.data` is `Optional[dict]`, not `Any` | **ACCEPT.** `web/response.py:33` (report says `:32`): `data: Optional[dict] = None`. The `Any` the PR body had in mind is the *function parameter* at `:60`, which lands in this field at `:71`. Reproduced: `dict → OK, data keys = 36` (matching the report exactly) vs `TASK_STATUS → ValidationError: Input should be a valid dictionary` |
| F401 genuinely red | **ACCEPT, exact.** `ruff check … execution.py` → `F401 '..types.task.TASK_STATE' imported but unused` at `:63:39`, **exit 1**. **Baselined:** develop's `execution.py` → exit 0, with `:63 from ..types.task import TASK_STATUS`. Introduced, confirmed |
| `extra='ignore'` drops new fields | **ACCEPT, demonstrated.** `types/task.py:295`; `grep -n model_config` over the file → **zero hits**, so pydantic's default `ignore` applies. Probe: raw dict exposes `queuePosition`; `TASK_STATUS` exposes it neither as attribute nor in `model_dump()`, and `model_extra is None`. Silently dropped |

**Mechanism nit in F1 (conclusion holds, citation wrong):** the report says the `AttributeError` is
caught by *"`_monitor`'s `except Exception` at `:158`"*. That except is at **`:161`**, and it does **not**
cover `:165` (outside the `try`). The `{ok: False}` envelope actually comes from `handlers.py:126` —
`HARD_EXC_NAMES` excludes `AttributeError`, so `normalize_error` produces it. Same outcome, wrong path.

---

## 12. #1866 — second blocking review · **ACCEPT ×2**

### Claim 13 — the 2026-09-03 review exists and applies to the current head — **ACCEPT, exact**

```
cmd : gh api repos/rocketride-org/rocketride-server/pulls/1866/reviews --paginate
id=5021817551 CHANGES_REQUESTED joshuadarron 2026-08-25T17:16:06Z commit=2dd54750b…
id=5106919644 CHANGES_REQUESTED joshuadarron 2026-09-03T21:18:26Z commit=fc81bb06f…   <-- current head
```

`gh pr view 1866` → head `fc81bb06f…`, `reviewDecision CHANGES_REQUESTED`, `state OPEN`, last commit
**2026-08-25T23:16:20Z** — nine days *before* the review. So the report's *"standing
CHANGES_REQUESTED is CURRENT, not stale — no commit since"* is right. All five rows of its §7 table
match the API. Merge-base `44b5190fc…`, **101 behind / 6 ahead**, `merge-tree` exit 0 with tree
`e2ce2178…` — byte-identical to the report's stated tree.

### Claim 14 — the contested clause — **ACCEPT: the reviewers' reading is right**

```
task_engine.py:340    self._pipelineTraceLevel = _args.get('pipelineTraceLevel', None)
task_engine.py:1551   if self._pipelineTraceLevel:
```

Both quotes exact. The raw value is stored, so omitted → `None` (falsy) but the string `'none'` is
**truthy**, and `:1551` is a plain truthiness test. **`_emit_tool_trace` call-site count = 6**
(definition `data_conn.py:844`; calls at `:949` BEGIN, `:981` ENTER, `:990` LEAVE/continue, `:1008`
LEAVE/skip, `:1010` LEAVE/error, `:1030` END). **None is gated on trace level** — decisive:
`grep -n "pipelineTraceLevel\|traceLevel\|trace_level" data_conn.py` → **0 hits**, and
`_emit_tool_trace` itself ends at `:875` with an unconditional `monitorOther('DBG', …)`.

The chain closes in source: `data_conn.py:875` → `transport_stdio.py:861` `'event': 'apaevt_trace'` →
`task_engine.py:1512` → the `:1551` gate → `_accumulate_analytics`, which populates
`componentStats[component_name]` on `operation == 'leave'` with **no tool/lane filter**. C++ half
confirmed: `endpoint.config.cpp:281-286` recognises only `metadata`/`summary`/`full`. Not executed —
the engine is unbuildable, and **both** the report and the review say so.

**A count discrepancy worth knowing:** the review body itself says *"called from **seven** sites"* and
then lists **six**. The report's "six" is the **correct** number — but it silently corrected the
reviewer while claiming to have *"verified every step of it independently"*. Worth stating explicitly,
since the corrected count is itself evidence the verification happened. Cite nits:
`pipe.instance.cpp:113` **does not exist** (`:52` and `:111` do), and the report omits the reviewer's
precise `transport_stdio.py:861`.

---

## Decision log — every disagreement with a primary

### D1. #1874 F2 severity — **I downgrade P2 → P3**

* **Primary:** *"the file carries a credential and is written with default permissions, though the repo
  writes 0600 elsewhere"* — P2, citing `service-linux.ts:118,158` / `service-mac.ts:100,137` as
  precedent for **credential-bearing** files.
* **Me:** the 0644 fact is right; the precedent is mischaracterised. Those four sites write a launchd
  plist and a systemd unit into a temp dir before `sudo cp` into a root-owned location. Grep of
  `buildPlist`'s body for `apikey|password|token|secret|credential` → **no match**. No credential; the
  0600 is TOCTOU hardening for a privileged install.
* **Settled by:** reading all four call sites and their content builders, plus the empirical mode check.
* **Outcome:** remediation unchanged and still worth doing; the *justification* must be rewritten.
  Severity P3 — the payload is the public default `'MYAPIKEY'`, and exposure needs a second local user
  with read access, strictly weaker than F1's write precondition.

### D2. #1908 F2 — **I upgrade the evidence, not the severity**

* **Primary:** F2's Postgres consequence is *reasoned*, and its own §8 flags that if psycopg2 +
  SQLAlchemy raise `PendingRollbackError` there, F2 would degrade P1 → P3.
* **Me:** executed it on a real throwaway PostgreSQL 16. They do **not** raise: `commit()` returns
  normally, the client is told `{ok: true}`, and the write is **discarded** — with a literal `COMMIT`
  on an aborted transaction visible in the server log.
* **Settled by:** execution. **F2 stays P1**, and the open question is now closed rather than open.

### D3. #1908 — **two DOWNGRADEs on supporting claims**

* *"v2 is a byte-copy of v1 plus …"* — **wrong**; ~23 % of the semantic delta is unrelated develop
  drift (pricing-card props) swept in by a 10-day gap between mints. Settled by reading the diff hunks.
* *"`shell:freeze --check` forces the mint"* — CI actually runs `shell:check`, and `--check` **never
  mints**; it exits 1 and tells you to run the freeze. Settled by reading `ci.yml:277-281` and
  `freeze-shell-api.js:829-847`. The blocking conclusion survives; the wording does not.

### D4. #1382 F3 — **the prescribed regression test is broken**

* **Primary:** add `expect(() => client.sendFiles(files, token, 0)).toThrow(RangeError)`.
* **Me:** develop's guard is inside an `async` function, so it **rejects**; executed, the assertion does
  not catch (`caught=false`), confirmed under jest-jasmine2. Must be `.rejects.toThrow`.
* **Settled by:** execution. As written the test would pass against a broken implementation.

### D5. #1382 F4 — **UPGRADE confidence, DOWNGRADE one phrase**

Leak raised MEDIUM-HIGH → **HIGH** (now runtime-measured: develop 3 pipes still open, PR 0). But
*"not returned to the pool's accounting"* is false client-side (measured) and only defensible as a
server-side claim, which is unverifiable here.

### D6. #2025 F5 — **the defect is real; its stated user-facing trigger is not**

* **Primary:** the empty ESM module is a hazard because *"Docs at `README-apps.md:125/146/165` show
  value-import forms without an adjacent 'requires Module Federation' warning"*, and the draft comment
  cites *"`import { connectionManager } …`"* from that doc.
* **Me:** those three lines are all **`import type`** — erased at compile time, so they cannot produce
  the runtime `SyntaxError` the finding describes. And the `connectionManager` example in that doc is
  at line 643, importing from **`'shell'`**, not from `rocketride/app-sdk`.
* **Settled by:** reading the cited lines. A genuine value-import-from-app-sdk form *does* exist —
  `src/app-sdk/index.ts:30` — so the hazard stands, but the rationale and the proposed docs fix are
  aimed at the wrong file. **DOWNGRADE** the impact framing; keep the finding.

### D7. #2025 F2 — **"introduced" is the wrong label**

* **Primary:** F2 is *"introduced (latent)"*, citing
  `packages/ai/src/ai/modules/mcp/apps/tsconfig.json:15`.
* **Me:** `git ls-tree -r d1f3add4 -- packages/ai/src/ai/modules/mcp/apps` returns **nothing** — the
  subtree postdates the PR branch point and exists only on develop.
* **Settled by:** the ls-tree. Correct label: *pre-existing config this PR invalidates in the merged
  state*. Impact unchanged (P3, dormant).

### D8. #1901 §5-E "none subclasses" — **factually wrong, conclusion survives**

`packages/ai/src/ai/common/models/base.py:269` is an in-repo subclass at ~18 call sites. Settled by
executing its exact `super().__init__` on both trees — ACCEPTED on both, because `module` and `ws_path`
are allowlisted. "Zero in-repo breakage" is right, but was reached without checking the one case that
could have falsified it.

### D9. #2117 F2 — **two of three take-theirs consequences REJECT**

* **Primary:** resolving the #2127 conflict by taking the PR's side loses the `hint`, leaks a developer
  checklist into end-user text, and reintroduces `mimetype=`.
* **Me:** executed the resolution. Only the **first** holds. The base lines that carried `msg` into
  `response` were deleted one-sidedly by develop, so they drop cleanly *outside* the conflict and `msg`
  is built then **discarded**; and develop's `mimetype=` → `mime_type=` fix is likewise one-sided, so it
  **auto-merges and survives** outside the markers.
* **Settled by:** `git merge-file` on the three stages plus reading the resolved file. Both rejected
  consequences hold only under a **whole-file** `git checkout --theirs`. The finding should name which
  resolution it means. Related: F2 is tagged "(reproduced)" but its evidence reproduced *PR-head*
  behaviour, not the merge outcome.

### D10. #2117 F3 — **cost over-stated ~6×**

* **Primary:** the substring false positive "retries 3× (≈4.8 s per F1)".
* **Me:** F1's 4.8 s assumes the engine's inner 10×150 ms loop re-runs per client attempt. In the
  remote-node path the data channel connects fine, `_data_client` is already set, and `task_engine.py:748`
  is skipped — real cost ≈ the 0.75 s client backoff.
* **Settled by:** reading the guard at `:748` against the finding's own scenario. The false positive
  itself is real; only its price tag is wrong. (Its last hop is also **unavailable**, not passed — the
  invoking code is in the unbuildable C++ engine-lib.)

### D11. #2011 F1 heading — **over-asserts what the body carefully hedges**

* **Primary heading:** "blocks a deploy API that **this repo's server implements on SaaS**".
* **Me:** there is no `packages/ai/src/ai/account/saas` in-tree; the SaaS override is out-of-tree and
  known only from docstrings. The body hedges this correctly in **five** places and explicitly calls
  the live-Cloud question *"an open question, not a finding"* — the heading does not.
* **Settled by:** `ls` on the path. Rewrite the heading; the body is fine.

### D12. #1866 — **the report silently corrected the reviewer, and was right to**

* **Review body:** `_emit_tool_trace` is *"called from **seven** sites"*, then lists six.
* **Report:** says six, while claiming to have *"verified every step independently"*.
* **Me:** counted — **six** (`:949, :981, :990, :1008, :1010, :1030`). The report is right, but the
  correction should be *stated*: the corrected count is itself the evidence that the verification
  happened.

### D13. #1874 F7 scope — **narrower than stated on the Python side**

`pid: 1.5` **is** rejected by the Python reader (reproduced). The float hole is TypeScript-only. The
finding stands; its Python half should not claim floats.

### D14. #1895 §5-D "peak 4" vs my "M1 = 5" — **no disagreement; instrument difference. Primary correct.**

My M1/M2 decrement only on `close()`, and the failed pipe is deliberately never closed. My M3 (fd proxy)
reads 4 and `o/c = 12/11` matches theirs. Recorded so nobody later reads my raw numbers as a conflict.

### D15. Duplicate analysis §3, develop row for internal cancellation — **wording, not a ruling**

Marks develop *"n/a"*; measured, develop returns `None_holes=[2]` — the same hole as #1895.
**"pre-existing"** is accurate. Does not change the keeper recommendation.

### D16. #1895 §5-B/§5-E — **my first run contradicted the primary; the primary was right**

My failures were caused by running without the repo's **root** `pyproject.toml`. With it: 16 passed,
ruff clean. **No disagreement** — logged because the near-miss is instructive.

---

## Validation audit — executed vs observed vs proposed

**Sweep for the forbidden pattern first.** I grepped every report for signals that a reviewer edited PR
implementation code to make validation pass (`edited the source`, `applied the fix`, `after fixing`,
`with my fix`, `to make it pass`, `modified the source`, `I changed the`, `edited the implementation`):
**no matches in any file.**

Stronger than a grep, for #1908: the verification agent **byte-compared** the reviewer's worktree against
a fresh `git archive` extraction at `060b52192` across all 9 touched files — including the two generated
files they ran `client-typescript:freeze` on — and found **all 9 IDENTICAL**, corroborating their
`git restore` claim. For #1002/#1382: both refs still at the reported SHAs, `ls-tree -r` finds no
review-temp artifacts, and `timeoutGuard.ts` at the ref is still the broken `Promise<void>` version.
Where reviewers added review-only artefacts they disclosed them and their removal (#1874's
`REVIEW_ONLY_discovery_harness.ts` in a temp extraction; #1895's copied cross-suite file, *"deleted after
the run"*; #1002's fix applied to a *copy*). I did the same and verified my copy was removed. **Clean.**

**Honesty markers are present in all 12 reports** (2–8 explicit "not run / unavailable / code inspection
only / cannot be built" markers each).

| Report | Audit result |
|---|---|
| **1874.md** | **Clean and unusually rigorous.** E1–E6 each carry command, tree, SHA, exit code, result and an *attribution* column. E2's failure is explicitly labelled `environment`, not a PR defect. The writer half is stated as *"never executed"*; Windows/Linux as *"code inspection only"*; F4 as *"not executable on this macOS host"*. The CI line explicitly warns the 18/18 green covers none of the TypeScript |
| **1895.md** | **Clean.** §5-B/C/D/E/F/G all give command + cwd + SHA + exit. Carries an explicit *"Validation unavailable (stated, not counted as a pass)"* block and — commendably — *"I did not attribute individual check runs to commits"*, a gap I have now closed. §5-F records and corrects **an earlier wrong run of its own** rather than burying it |
| **2004.md** | **Clean.** Every block labelled "executed locally" with exit codes. Corrects the PR body's own test count. The `ruff` attribution uses a whole-repo control (2 of 1536 files, both in the diff); I reproduced that reasoning with a develop-side control on the same file |
| **duplicate-analysis** | **Clean.** Flags its own most load-bearing classification and warns the verifier that misreading it inverts the recommendation. The fairness note on the AI-agent author is properly walled off from the technical comparison |
| **1901.md / branch-recovery** | **Clean on executed-vs-proposed.** CI observations labelled as CI and independently confirmed. **One unreproducible-but-corroborated item:** the lefthook pre-commit transcript in branch-recovery §4 ran in worktrees since removed; the substance checks out (`lefthook.yml:19-21` runs `ruff format --check {staged_files}`, and that command does fail on that file). "Introduced" classifications are baselined |
| **1908.md** | **One real mislabel.** F2's `Actual (executed):` bullet runs sqlite-*executed* and Postgres-*reasoned* together under a single "(executed)" tag. §5 corrects it honestly, but a reader of §4 alone would be misled. (Substance now confirmed by execution anyway.) §3a's `shell:check → exit 0` is **corroborated, not re-executed** (needs a full workspace install). **F1 asserts "introduced" without a baseline** — classification correct, evidence supplied by me. F7 is the good case: they ran develop, found the same failure, and **corrected their own attribution in writing** |
| **1382.md / 1002.md** | **Clean.** Both separate Executed / CI-observed / Proposed, state the HTTP 410 log expiry, and explicitly *refuse* CI attribution (*"I am explicitly not attributing them"*). #1382 §3 pre-declares its runtime gap as *"validation unavailable, not a pass"*. **#1002 F1 asserts "introduced" without running the baseline** — correct, but unestablished by its own evidence; I closed it (74 → 0 tests). Minor softness: #1382 F2's *"I traced `files = []` through both"* is manual reasoning phrased near executed rows |
| **2025.md** | **Clean on executed-vs-observed** — §5 separates Executed / CI-observed / Proposed and labels the unrunnable builder *"validation unavailable, never a pass"*. Every artifact named in §5 exists and byte-matches an independent re-download. **One wrong "introduced" label (F2)** — its cited `tsconfig.json` does not exist at the reviewed head; correct label is pre-existing-on-develop. **One finding cited to the wrong evidence (F5)** — see §6 |
| **2117 / 2011 / 2007 / 1866** | **Clean overall**; all four carry explicit Executed / CI-observed / Proposed sections, and #1866 states outright that nothing was executed. **One flag: #2117-F2 is tagged "(reproduced)"** on a claim about the *merge* outcome while its evidence reproduced *PR-head* behaviour — and the merge outcome materially differs (§9). #2007-F1/F2's "reproduced" tags are for isolated expressions, which §5 discloses. **No "introduced" lacks a baseline** — I re-ran both lint baselines (develop's `deploy.py` formats clean; develop's `execution.py` lints clean). #2117-F1 correctly labels its 4.8 s as arithmetic, not measured |

**CI attribution — checked on all 12 heads, no misattribution found.** `inventory.md` itself warns
*"reviewers must attribute check runs to commits themselves before trusting them."* Verified at the head
SHA:

| PR | head | success | failure | skipped | report says |
|---|---|---|---|---|---|
| #1895 | `a75c20ef8` | 20 | 0 | 4 | "20 ok / 0 fail" ✔ |
| #2004 | `0078e6413` | 11 | 2 (`Ruff`, `CI OK`) | 4 | "Ruff FAILURE → CI OK FAILURE" ✔ |
| #1901 | `58990420b` | 16 | 2 (`Ruff`, `CI OK`) | 4 | "16 ok / 2 fail" ✔ |
| #2025 | `d1f3add47` | — | **5** | — | "5 fail" ✔, and CI provably tested the head **tree** (`Merge d1f3add4 into 1b3943231` = its own parent) |
| #2117 | `e4d4a858c` | 18 | 0 | 4 | "18 green" ✔ |
| #2011 | `49716a0dc` | 14 | 2 (`Ruff`, `CI OK`) | 4 | "14 ok / 2 fail" ✔ |
| #2007 | `f96da1508` | 16 | 2 (`Ruff`, `CI OK`) | 4 | "16 ok / 2 fail" ✔ |
| #1866 | `fc81bb06f` | 16 | 0 | 4 | "16/16 green" ✔ |

The lead's note that #1382/#1002 CI logs expired (HTTP 410) and are therefore unattributable is correct
and correctly acted on. One cosmetic slip found: #2025 attributes `check-externals (PR)` to run
`32079323156`; it belongs to run `32079322947`.

**A "green CI" caveat the reports flag and I confirm.** For #2025 the *failing* checks were also checked
against develop to rule out stale-base flake: develop @ `973cd9b4` carries an independent
`Build / Ubuntu 22.04` failure, but its log is an unrelated apt/network error — different root cause, no
overlap. That control is the right one and it holds.

**Line-number drift is the one systemic weakness, and it is repo-wide.** Every reviewer's content is
right while the pointers drift 1–5 lines, and #1901's drift ~50 because develop's numbering was used for
a PR-head file. Harmless in analysis; **not** harmless in the draft GitHub comments, which point authors
at specific lines. Corrected set:

| Report | Cited | Actual |
|---|---|---|
| #1895 | `:491` · `:512` · `cli/main.py:402` | `:492` · `:517` · `cli/main.py:413` |
| #1901 | `:191-196` · `:258` · `:468` | `:205-210` · `:305` · `:515` |
| #1908 | `tx_registry.py:39` · `writeApiVersion` 534 | `:54` · 533 |
| #1382 | `client.ts:1473-1474` | `:1479-1480` |
| #1874 | develop doc `:1113-1114` | `:1112-1113` |
| #2117 | `data.py:71-72` · `data.py:54` · `transport_websocket.py:378/411` | `:73-74` · `:56` · `:377/410` |
| #2011 | `deployment_backend.py:23-24` · `account/base.py:53` · `ci.yml:338` | `:23-25` · `:55` · `:335` |
| #2007 | `response.py:32/70` · `visibility.py:158` | `:33/71` · `:161` |
| #1866 | `task_engine.py:1561/1568/1571` · `pipe.instance.cpp:113` | `:1560/1567/1570` · **does not exist** |

**Two proposed regression tests are broken as written** — #1382 F3 (needs `.rejects.toThrow`; as written
it silently passes against a broken implementation) and #1908 F5 (the stated case already passes at
head; the bug needs a backslash inside the literal). Both would ship tests that never fail.

**Two findings cite the wrong evidence for a real defect** — #2025 F5 (its three cited doc lines are
`import type`, which cannot produce the runtime error described) and #2117 F3 (cost over-stated ~6×).
The defects are real; the rationales need rewriting before they go to an author.

**One cross-report inconsistency, resolved in the reports' favour.** `1895.md` §7 says *"No overlap with
… #1901"* while `overlap-matrix.md` lists 4 shared files including `mixins/data.py`. Both are right at
different resolutions: the matrix is **textual** (and says so), computed over #1901's polluted 609-file
three-dot list; #1901's **real** net change is 2 files and does **not** include `mixins/data.py`
(verified). **The lead should use the two-dot view for #1901 in merge planning.**

**Cross-PR edge, checked rather than assumed.** `tasks.md:15` already lists *"1901↔1874 share
client.py"* as a merge-plan hard edge, though neither per-PR report mentions the other. It is
semantically real — #1901 installs a strict 16-name `_KNOWN_CONSTRUCTOR_KWARGS` allowlist in the same
constructor #1874 rewrites. I tested it:
`git merge-tree --write-tree --messages refs/review-12prs/1874 refs/review-12prs/1901` → **exit 0**,
`Auto-merging packages/client-python/src/rocketride/client.py`. **Benign** — they merge cleanly and
#1874 adds no kwarg for the allowlist to reject.

---

## Verdict deltas

**No PR's verdict changes. All primary verdicts stand.**

| PR | Primary verdict | My ruling |
|---|---|---|
| #1895 | READY (pending review refresh) | **stands — confirmed and strengthened** |
| #1874 | CHANGES REQUIRED | **stands** (F1/F3/F4 remain blocking) |
| #2004 | close as duplicate | **stands** |
| #1908 | CHANGES REQUIRED + rebuild/split | **stands** (both P1s confirmed; F2 now executed) |
| #1382 | REDUNDANT | **stands** |
| #1002 | CHANGES REQUIRED | **stands** |
| #1901 | REBUILD (replay route) | **stands** |
| #2025 | CHANGES REQUIRED | **stands** (P1 root cause proven; CI chain closes) |
| #2117 | CHANGES REQUIRED, rebase-and-keep | **stands** (not redundant; conflict real) |
| #2011 | CHANGES REQUIRED | **stands** (premise contradiction confirmed in-tree) |
| #2007 | CHANGES REQUIRED | **stands** (9/9 consumer sites break; F401 red) |
| #1866 | CHANGES REQUIRED | **stands** (blocking review is current, not stale) |

**Severity / evidence deltas within unchanged verdicts:**

* **#1874 F2: P2 → P3.** The 0600 "house rule" precedent does not exist; the cited files carry no
  credential. Remediation unchanged, justification must be rewritten.
* **#1874 F7: scope narrowed.** Python rejects float pids; the float hole is TypeScript-only.
* **#1908 F2: reasoned → EXECUTED, stays P1.** The report's own P1→P3 degradation risk is now closed
  against degradation.
* **#1908: two supporting claims downgraded** — the "byte-copy of v1" characterisation (~23 % is
  unrelated drift) and the "`shell:freeze --check` forces the mint" wording (CI runs `shell:check`;
  `--check` blocks, never mints). Plus a new defect: v2.d.ts's provenance header names a commit whose
  tree does not contain the file's content.
* **#1382 F4: MEDIUM-HIGH → HIGH** (now runtime-measured); F4's "pool's accounting" phrasing dropped;
  **F3's regression test must be rewritten to `.rejects.toThrow`**.
* **#2025 F5: impact evidence downgraded.** The defect is real, but its three cited doc lines are
  `import type` (erased at compile time) and the `connectionManager` example imports from `'shell'`, not
  from `rocketride/app-sdk`. Re-cite to `src/app-sdk/index.ts:30` and move the proposed docs fix.
* **#2025 F2: "introduced" → pre-existing-on-develop.** The cited `tsconfig.json` does not exist at the
  reviewed head. Impact unchanged (P3, dormant).
* **#1901: forwarding-subclass severity framing softened** — the PR restores stock cooperative
  `__init__` behaviour; develop's tolerance was an artifact of a non-cooperative base.
* **#2117 F2: two of three consequences REJECT.** Under a *hunk-level* take-theirs only the `hint` is
  lost — the checklist text is built then discarded, and develop's `mime_type=` fix auto-merges and
  survives. The finding must say it means a **whole-file** `checkout --theirs`.
* **#2117 F3: cost over-stated ~6×** (≈0.75 s, not ≈4.8 s), and its last hop is **unavailable**, not
  passed — the invoking code is in the unbuildable engine-lib.
* **#2011 F1: heading over-asserts.** No `account/saas` exists in-tree; the body hedges correctly in
  five places, the heading does not. Reword the heading only.
* **#2011 F1: "loses `client.deploy`" is wrong wording.** The namespace object exists; all 16 methods
  raise. Practical effect unchanged.
* **#2007 F1: mechanism citation wrong** (`except` is at `:161` and does not cover `:165`; the
  `{ok:false}` envelope comes from `handlers.py:126`). Conclusion holds.

**Additions for the lead:**

* **#1895 survives the merge, not just the head.** I merged it into develop in-memory (tree
  `9b4cf4192…`) and re-ran everything: identical bounds (5/5, limit-1 serial, no holes, order kept) and
  **72 passed / 21 errors**, matching both the PR head and develop's own error set.
* **#1895 has no regression in the full runnable suite** — 72 passed vs develop's 56 + 16 new, with an
  identical set of 21 server-backed errors. Beyond what the primary produced.
* **#1874 ↔ #1901 checked and benign** (clean auto-merge, no kwarg collision).
* **Draft GitHub comments should not be posted as written**: the line numbers in the table above, the
  two broken regression tests, and the two mis-cited rationales (#2025 F5, #2117 F3) all need a pass
  first.

---

## Head SHA drift re-check (end of verification)

`gh pr list --repo rocketride-org/rocketride-server --state open --json number,headRefOid` compared
against `git for-each-ref refs/review-12prs/`:

| PR | local ref | GitHub headRefOid | |
|---|---|---|---|
| #1002 | `5b2d9aa868c3b9dc3f5f8b2d8980d3ad607899cf` | same | MATCH |
| #1382 | `3bf793390f432b46eb60f38363341cecf3e27110` | same | MATCH |
| #1866 | `fc81bb06fd0b58f84123064429c593f190d0e37a` | same | MATCH |
| #1874 | `d1417095a2174caa7014e09d32e167f03a644a09` | same | MATCH |
| #1895 | `a75c20ef817b8333f1ae30ab7c28c2a81fc888f7` | same | MATCH |
| #1901 | `58990420bfd6f7b2f8d1f33826c6f4884fd845a9` | same | MATCH |
| #1908 | `060b52192e9eb3a2558cbb4fbe090178e73d043b` | same | MATCH |
| #2004 | `0078e6413767c88648d8e7f388b8bbf3825cbe37` | same | MATCH |
| #2007 | `f96da15089e5852508c1e814bbfa2dc8ce6470c0` | same | MATCH |
| #2011 | `49716a0dc2ef882e8cbb4a3a5d572b8fba914994` | same | MATCH |
| #2025 | `d1f3add4760d6b92a1451a71aa85bf5332b8c0ac` | same | MATCH |
| #2117 | `e4d4a858c4e5e9da2ba74609af41c276aa4bd249` | same | MATCH |

**No drift on any of the 12.** Every finding in this document and in the primaries' reports still
attaches to the live head.
