# PR #2005 review — fix: prefer IPv4 socket in WebServer.get_port() (#994)

Reviewer: networking-reviewer | Head: `e8379b596f4bf21d17a059c927dc133dd6c96a86` (re-verified live via gh at review end) | Merge-base: `4a72f8d142` | develop: `9a5fc5c8c0` (merge-tree clean, re-confirmed locally) | 2 commits: `5ec27e5a` (fix), `e8379b59` (test-helper docstrings) | Files: `packages/ai/src/ai/web/server.py` (+25/-6), `packages/ai/tests/ai/web/test_server.py` (+104/-0)

Location note: written to the reviewer's isolated worktree (`.claude/worktrees/agent-afb2baf4ed4c04ed6/.review-cpu-net/`) because the shared `.review-cpu-net/` path is write-protected for worktree-isolated agents.

## 1. Intended behavior (from #994 + the public API)

Issue #994 (P2, later re-prioritized Low by asclearuc): with default `host=localhost`, `port=0` on a dual-stack host, uvicorn binds one socket per address family and the kernel assigns **different** ephemeral ports. `get_port()` returned whichever socket uvicorn enumerates first; the four in-process `task_http` callers build `http://localhost:<port>`, so a client whose `getaddrinfo` tries the other family first gets a refused first attempt. Today this self-heals (`websockets` iterates addrinfos): shipped symptom = extra connect attempt + `[WinError 1225]`-style log noise + fragility for non-fallback clients, **not** a hard failure.

Two claims must be kept separate:

- **Claim A — `get_port()` returns an IPv4 port when one exists.** This is issue #994's "Proposed Approach 1", which the author announced on the issue (2026-08-16 comment) and implemented. It is a valid contract for `get_port()` itself: the API promises "the port number actually bound by uvicorn" — a port, not reachability.
- **Claim B — the URL the caller builds is first-attempt reachable by the actual client.** This is the issue's literal "Expected" statement: "connects on the first attempt, regardless of which address family `getaddrinfo` returns first."

**Resolution of A vs B:** the issue text requires B; the issue's own menu of approaches admits A ("pick one in the resolving PR"), but approach 1 cannot deliver B by itself — port choice does not control client-side `localhost` resolution. I verified this by experiment (§4c): with an IPv4-only listener and an IPv6-first resolver, the real asyncio client stack makes a refused `[::1]` attempt before succeeding on `127.0.0.1`. So the PR fully delivers A and improves B only from "coin flip on uvicorn enumeration order" to "deterministically wrong-family-first on IPv6-first hosts / deterministically right on IPv4-first hosts." No API redesign is needed to close the gap: the standing review's option (a) (a `get_local_uri()` sibling + four one-line caller edits) meets B, and option (b) (re-scope `Fixes` → `Refs`) makes the PR honest without meeting B. Either is proportionate; nothing larger is warranted.

## 2. The CHANGES_REQUESTED review — current or stale?

**Current in every dimension.** `gh api .../pulls/2005/reviews` shows exactly one review: joshuadarron (COLLABORATOR), CHANGES_REQUESTED, `submitted_at 2026-08-18T18:40:01Z`, **`commit_id = e8379b596f...` — the current head**. PR `updatedAt` equals the review timestamp; head commits are dated 2026-08-16; there are zero inline review threads (`reviewThreads: []`), zero author replies (PR comments are only the Discord-sync bot and CodeRabbit), and the body still opens **`Fixes #994`**.

What it asked, and status at this head:

| Ask | Blocking? | Status at `e8379b596` |
|---|---|---|
| Pick (a) add `get_local_uri()` + record family in `_set_port` + update 4 `task_http` callers, **or** (b) keep patch, change `Fixes #994` → `Refs #994` + scope body honestly | **Yes** ("the one thing I want to resolve before merge"; "say which you'd like and I'll re-review promptly") | **Not addressed.** No caller files in the PR; body still `Fixes #994`; no reply choosing either. |
| Tests for the `OSError → continue` path and the non-tuple (`AF_UNIX`) `getsockname()` guard | No | Not added (behaviors verified working — §4d). |
| One-line comment on the `monkeypatch.delenv` teardown subtlety in `test_rr_base_url_behaviour` | No | Not added. |
| Docstring nit: the `>>> port = get_port()` / `5565` example could note the dual-stack case returns the IPv4 port (the prose at L803-805 does say it; the Example block at L810-812 doesn't) | No | Not addressed. |

The reviewer's own verification of the patch (AST-extracted source run against real sockets, incl. closed-socket and unix-socket cases; ruff clean on both files) is consistent with everything I measured independently.

## 3. Implementation assessment

Diff verified at head ([server.py L788-L835](https://github.com/rocketride-org/rocketride-server/blob/e8379b596f4bf21d17a059c927dc133dd6c96a86/packages/ai/src/ai/web/server.py#L788-L835)):

- `get_port()` scans `self.server.servers[*].sockets`, **early-returns the first `AF_INET` socket's port**, records the first non-IPv4 valid port as `fallback_port`, and returns the fallback only after the full scan finds no IPv4. The `try/except OSError → continue` and `isinstance(bound, tuple) and len(bound) >= 2` guards are **pre-existing** (unchanged diff context), not new hardening added by this PR.
- `_set_port(port)` extraction: sets `self._port`, conditionally publishes `RR_BASE_URL` — the same condition (`if not os.environ.get('RR_BASE_URL')`) and f-string shape as the old inline code and as the startup path at L485-487. **No new side effect introduced**; empty-string env value overwritten before and after (identical expression; also executed at head, §4d).
- Initialization safety: `__init__` sets `self._port = None` (L279) and `self.server = self._configure_server()` (L351); `_configure_server` assigns `_base_url_scheme`/`_base_url_host` (L483-484) before the server object exists — `_set_port` cannot hit AttributeError via any real flow, and the guard `if not self._port and self.server is not None` keeps configured non-zero ports authoritative without a scan.
- Callers unchanged: `task_cancel.py:24/28`, `task_status.py:27/31`, `task_data.py:512`, `task_exec.py:65` still build `f'http://localhost:{port}'` — the literal `localhost` stays on the hot path (the crux of §1's claim-B gap).
- Assessment: **the change is correct, minimal, and does exactly what it says.** Every code path in the review checklist behaves correctly under execution (§4d). The defect is not in the code — it is in what the PR claims the code resolves.

## 4. Test + connectivity evidence

### a. Validation record (executed)

- **cwd:** `/Users/nihalnihalani/Desktop/Github/rocketride-server/.claude/worktrees/agent-afb2baf4ed4c04ed6` (isolated review worktree, detached at `e8379b596f4bf21d17a059c927dc133dd6c96a86`)
- **Env:** isolated scratch venv — Python 3.14.3, pytest 9.1.1, pytest-asyncio 1.4.0, pytest-timeout 2.4.0, fastapi 0.141.1, uvicorn 0.52.4, websockets 17.1 (macOS, Darwin 25.5.0). Loopback-only sockets throughout; no fixed sleeps (readiness = `listen()` return; refusals are immediate loopback RSTs). Nothing installed into the user's environment.
- **Harness accommodation (disclosed):** a focused run of `test_server.py` alone errors in **all 16 tests at setup** — `packages/ai/tests/conftest.py:24` (`from ai.account.store import Store`, autouse fixture) collides with the module's pre-existing inject-if-absent `_inject('ai.account', MagicMock())` preamble. This is **pre-existing** (both the preamble and the conftest fixture are untouched by this PR) and masked in full-suite/CI runs where `tests/ai/account/*` imports the real `ai.account` first. I reproduced the CI ordering with a preload plugin that imports the real `ai.account.store` up front, shimming only the engine-bound `depends`/`rocketlib` (both genuinely require the engine's `engLib`, unavailable here; shimming them is the test file's own established practice). The C++ engine is not buildable in this sandbox; these tests are pure-Python and were run for real.

| Run | Command (via sys.path wrapper equivalent to `PYTHONPATH=packages/ai/src:packages/client-python/src`) | Result | Exit |
|---|---|---|---|
| Full module at head | `python -m pytest packages/ai/tests/ai/web/test_server.py -p preload_ai_account -q` | **16 passed, 0 failed, 0 skipped** in 0.02s | 0 |
| Focused group at head | `... test_server.py::TestGetPort -p preload_ai_account -v` | **3 passed, 0 skipped** (`test_dual_stack_prefers_ipv4`, `test_ipv6_only_falls_back`, `test_rr_base_url_behaviour`) | 0 |
| Baseline: both files at merge-base `4a72f8d14` | same module command | **13 passed** | 0 |
| Bug-detection: merge-base `server.py` + head tests | `::TestGetPort` | **1 failed** (`test_dual_stack_prefers_ipv4`), 2 passed | 1 |

IPv6 loopback **is** bindable in this sandbox, so no coverage was lost to skips — the dual-stack and IPv6-fallback tests ran against real sockets, not skip paths.

### b. PR-body claims vs current-head execution

Body claims full-suite "identical except `1557 passed` → `1560 passed`". The full suite is engine-bound (the official runner uses `dist/server`'s Python) and **could not be run here — that figure is unverified as stated**. The module-level equivalent I executed matches exactly: 13 → 16 passed, delta = precisely the 3 new tests, and the new preference test fails against the old implementation — so the tests are real regression tests, not tautologies. The body's design claims (IPv6 listed first; skip-not-error on unbindable IPv6 since `socket.has_ipv6` is build-time only; `RR_BASE_URL` semantics unchanged) all verified true at head.

### c. Connectivity experiment (claim B) — executed

Deterministic loopback experiment (`connectivity_2005.py`), no sleeps: real IPv4 socket **listening** on `127.0.0.1:P`; verified nothing listens on `[::1]:P` (a probe re-rolls P on any non-refusal outcome); then the real client stack — `asyncio.open_connection('localhost', P)` (asyncio streams; `websockets`≥14 sits on them) with the event loop's `getaddrinfo` pinned IPv6-first, i.e. the resolver order #994 reports for Windows 11:

```
attempt ('::1', 51945, 0, 0) -> refused(61)
attempt ('127.0.0.1', 51945) -> ok
```

**First attempt refused on the wrong family, sequential fallback succeeded** — the exact "extra connect attempt + eventual success" symptom, reproduced against the IPv4 port this PR selects. Direct per-family connects confirm the split (`[::1]:P` → `ConnectionRefusedError`; `127.0.0.1:P` → success). Notably, **this macOS host's natural `getaddrinfo('localhost')` order is `['IPv6', 'IPv4']`** — the wrong-family-first behavior is not a Windows quirk; unmodified macOS resolvers hit it too. (Method note: macOS drops SYNs to a bound-but-not-listening socket rather than RST-ing — observed as a 5s timeout — so refusal is guaranteed via an unbound `[::1]:P` with a self-validating probe, not a blocker bind.)

This experiment **proves the mechanism** of the standing review's blocking claim. What it does not prove: behavior under Windows' actual resolver (evidence for that is the review's own on-platform verification plus #994's repro steps) — but the mechanism is resolver-order-generic, so this limitation does not weaken the conclusion.

### d. Reviewer's degenerate-state harness at head — executed, 23/23 PASS

`harness_2005.py` imports the real `WebServer` (same mock preamble as the test file) and executes: IPv6-listed-first; IPv4 in a **later server object**; multiple eligible IPv4 (first wins); multiple IPv6 only (stable first-IPv6 fallback, repeatable); closed socket first and mid-list (`getsockname` raises `OSError` on macOS — skipped without killing later sockets); `AF_UNIX` socket (`getsockname() == ''`, non-tuple → skipped); `self.server = None`; `servers` missing/None/empty; `sockets` missing/None/empty; all-dead scan → returns 0, **does not cache**, does not publish `RR_BASE_URL`, and recovers once a socket appears; configured non-zero `_port` short-circuits (sockets present but unconsulted, no `RR_BASE_URL` publish — matching old semantics, where startup publishes for non-zero ports at L485-487); discovered port cached across a server-object swap; `RR_BASE_URL` empty-string overwritten / scheme+host retained / built from the resolved IPv4 port; IPv6 `getsockname` 4-tuple parsed correctly. **All 23 checks passed** (exit 0). No socket-object shapes uvicorn can't produce were treated as production defects; the degenerate containers are defensive-guard checks only.

### e. What the executed tests prove vs don't

The new tests use **real bound sockets** (proving address/port ownership and real `getsockname`/`family` behavior) inside a **stubbed uvicorn container** (`SimpleNamespace(servers=[...sockets...])`, proving selection logic against the attribute shape production code reads) on the **real `WebServer.get_port()`** (via `object.__new__`). None of them listen or connect: **they prove claim A (selection), not claim B (first-attempt connectivity)** — §4c covers B separately. Distinct-port observability is enforced (explicit skip if the kernel assigned equal ports), and IPv6-first ordering makes preference — not list position — the thing under test, confirmed by the bug-detection leg (§4a row 4).

## 5. Findings

**PR2005-F1 — `Fixes #994` closes the issue without delivering its stated contract; the standing CHANGES_REQUESTED review at this exact head blocks on it.**
Severity **P2**, confidence **high**. Introduced by this PR (the closure claim; the underlying symptom is pre-existing).
Where: PR body line 1 (`Fixes #994`); callers unchanged at head — [task_cancel.py#L24-L28](https://github.com/rocketride-org/rocketride-server/blob/e8379b596f4bf21d17a059c927dc133dd6c96a86/packages/ai/src/ai/modules/task_http/task_cancel.py#L24-L28), [task_status.py#L27-L31](https://github.com/rocketride-org/rocketride-server/blob/e8379b596f4bf21d17a059c927dc133dd6c96a86/packages/ai/src/ai/modules/task_http/task_status.py#L27-L31), [task_data.py#L512](https://github.com/rocketride-org/rocketride-server/blob/e8379b596f4bf21d17a059c927dc133dd6c96a86/packages/ai/src/ai/modules/task_http/task_data.py#L512), [task_exec.py#L65](https://github.com/rocketride-org/rocketride-server/blob/e8379b596f4bf21d17a059c927dc133dd6c96a86/packages/ai/src/ai/modules/task_http/task_exec.py#L65).
Trigger: merge as-is → GitHub auto-closes #994. Expected (issue): first-attempt connect regardless of resolver family order. Actual (proven §4c): on IPv6-first hosts the in-process client's first attempt is now **deterministically** refused (`refused(61)`, then fallback). Consequence: the issue closes while its shipped symptom (extra attempt, `WinError 1225` log noise, fragility for non-Happy-Eyeballs clients) persists; on IPv6-first hosts the noise becomes every-time instead of a coin flip (the determinism is otherwise a genuine improvement, as the review itself acknowledges).
Smallest fix: **option (b)** — edit the body `Fixes #994` → `Refs #994` plus one scoping sentence, and reply to the review (no code change; unblocks re-review immediately). Reviewer-preferred: **option (a)** — record family in `_set_port`, add `get_local_uri()`, four one-line caller edits (note: the co-located documentation rule means a new public `get_local_uri()` also needs the corresponding package doc touch in the same change).
Regression criterion: for (a), the §4c experiment run against the new URI yields exactly **one** connect attempt under an IPv6-first resolver; for (b), #994 remains open after merge.

**PR2005-F2 — reviewer-requested coverage not added: `OSError → continue` path and non-tuple (`AF_UNIX`) guard; also uncovered: multi-server-object, cached-port, configured-port contracts.**
Severity **P3**, confidence high. Coverage gap only — the guards pre-date the PR and all behaviors are **verified correct by execution** (§4d, 23/23). Where: [test_server.py#L305-L360](https://github.com/rocketride-org/rocketride-server/blob/e8379b596f4bf21d17a059c927dc133dd6c96a86/packages/ai/tests/ai/web/test_server.py#L305) (`TestGetPort` has only 3 cases). Smallest fix: fold harness scenarios (closed socket, AF_UNIX, later-server-object, cached/configured port) into `TestGetPort`. Regression criterion: a refactor breaking the skip-continue or caching contract fails a test instead of shipping silently.

**PR2005-F3 — fixture sockets allocated before `try`: the IPv4 socket is not explicitly closed when the IPv6 helper skips.**
Severity **P3**, confidence high. Introduced (new test code). Where: [test_server.py#L311-L312](https://github.com/rocketride-org/rocketride-server/blob/e8379b596f4bf21d17a059c927dc133dd6c96a86/packages/ai/tests/ai/web/test_server.py#L311-L312) — `ipv4 = _bind_ipv4()` then `ipv6 = _bind_ipv6()`, both before the `try`; a skip raised inside `_bind_ipv6` (L272-287, which does close its **own** socket on bind failure) leaves `ipv4` to CPython refcount cleanup at frame teardown (a ResourceWarning at most; no cross-test port exhaustion). Explicitly a fixture-cleanup nit, **not** production severity. Smallest fix: bind IPv6 first, or move the IPv4 bind inside the `try`. Regression criterion: no ResourceWarning under `-W error::ResourceWarning` on an IPv6-less runner.

**PR2005-F4 — `test_rr_base_url_behaviour` relies on `monkeypatch.delenv` undo to clean a variable set by production code; un-commented.**
Severity **P3**, confidence medium (correct today — verified by the human reviewer and by my 16-test run showing no leakage; the risk is a future edit dropping the `delenv`). Introduced (new test). Where: [test_server.py#L342-L360](https://github.com/rocketride-org/rocketride-server/blob/e8379b596f4bf21d17a059c927dc133dd6c96a86/packages/ai/tests/ai/web/test_server.py#L342). Smallest fix: the one-line comment the review asked for. Regression criterion: removing the `delenv` makes `RR_BASE_URL` leak into subsequent tests.

**Pre-existing limitations (classified separately — none block this PR):**
- **Unbracketed IPv6 literal host in `RR_BASE_URL`**: `f'{scheme}://{host}:{port}'` with an operator-configured `host='::1'`/`'::'` yields an invalid URL (`http://::1:8080`). Pre-existing at [server.py#L487](https://github.com/rocketride-org/rocketride-server/blob/e8379b596f4bf21d17a059c927dc133dd6c96a86/packages/ai/src/ai/web/server.py#L487) and inherited verbatim by `_set_port` at [L793](https://github.com/rocketride-org/rocketride-server/blob/e8379b596f4bf21d17a059c927dc133dd6c96a86/packages/ai/src/ai/web/server.py#L793); the default config never reaches it. Candidate follow-up ticket, not a #2005 ask.
- **`test_server.py` is not isolated-runnable**: focused invocation → 16 setup errors via `conftest.py:24` vs the module's mock preamble (§4a). Pre-existing; masked by full-suite collection order.
- The #994 symptom itself (extra attempt + log noise) — the subject of F1's scoping, not a defect introduced here.

No further defects found. For the production code path itself, a no-defect conclusion is the honest result: selection logic, caching, degenerate-state handling, and `RR_BASE_URL` semantics are all correct, and each is either regression-tested or harness-verified at this head.

## 6. Merge verdict — **CHANGES REQUIRED**

Exactly what blocks: **PR2005-F1** — the standing, current-head CHANGES_REQUESTED review requires the author to choose (a) `get_local_uri()` + caller edits or (b) the `Fixes` → `Refs` re-scope, and neither has happened; the review is not stale and cannot be treated as overtaken by events. Everything else is verified sound: CI fully green at `e8379b596` (CI OK 2026-09-03, incl. Ruff and Ubuntu/Windows/macOS builds; CodeRabbit "no actionable comments"), `mergeable: MERGEABLE` / `mergeStateStatus: BLOCKED` (review gate), merge-tree onto develop `9a5fc5c8` clean despite 79-behind (re-confirmed locally), and 16/16 module + 3/3 focused + 23/23 harness + connectivity-mechanism runs all pass at head.

Material limits of this review: the full `packages/ai/tests` suite (body's 1557→1560 figure) is engine-bound and was not independently re-runnable — verified at module level only (13→16, delta = the new tests); Windows resolver behavior is taken from the review's on-platform evidence plus #994's repro, with the mechanism (not the platform) reproduced here; `depends`/`rocketlib` were shimmed per the codebase's own test practice (both need the engine's `engLib`).

## 7. Comment-input (hard facts for the comment writer)

1. The CHANGES_REQUESTED review (joshuadarron, 2026-08-18T18:40Z) was submitted against **the current head** — `commit_id e8379b596f4bf21d17a059c927dc133dd6c96a86` per `gh api repos/rocketride-org/rocketride-server/pulls/2005/reviews` — and nothing has changed since: no pushes, no replies, no body edit. It is current, not stale.
2. Neither offered resolution is present at head: option (a)'s files are absent from the PR (only `server.py` + `test_server.py` changed; all four callers still build `f'http://localhost:{port}'` — [task_cancel.py#L24-L28](https://github.com/rocketride-org/rocketride-server/blob/e8379b596f4bf21d17a059c927dc133dd6c96a86/packages/ai/src/ai/modules/task_http/task_cancel.py#L24-L28)), and option (b)'s one-line body edit (`Fixes #994` still opens the body) hasn't been made.
3. The patch itself is verified sound at head: focused `TestGetPort` **3/3 passed, 0 skipped** and full module **16/16** (Python 3.14.3, pytest 9.1.1, real IPv6 loopback available), plus a 23/23 execution harness covering IPv6-first, IPv4-in-a-later-server-object, multiple eligible sockets, closed-socket `OSError` skip, `AF_UNIX` non-tuple skip, empty/None/missing containers, no-cache-on-failure + recovery, configured-port short-circuit, cached discovery, and `RR_BASE_URL` preserve/empty-string/scheme-host — [server.py#L788-L835](https://github.com/rocketride-org/rocketride-server/blob/e8379b596f4bf21d17a059c927dc133dd6c96a86/packages/ai/src/ai/web/server.py#L788-L835).
4. The new dual-stack test genuinely detects the old bug: run against merge-base `4a72f8d14`'s `server.py`, `test_dual_stack_prefers_ipv4` **fails** (1 failed, 2 passed) — it observes family preference, not list position.
5. Module-level before/after matches the body's claim shape: 13 passed at merge-base → 16 at head, delta exactly the 3 new tests (the body's full-suite 1557→1560 figure is engine-bound and was not independently re-runnable).
6. The review's blocking analysis reproduces by experiment: with a real IPv4-only listener on port P and an IPv6-first resolver, `asyncio.open_connection('localhost', P)` makes **two** attempts — `('::1', P)` `refused(61)`, then `('127.0.0.1', P)` ok. The PR delivers "get_port returns the IPv4 port" but not #994's "connects on the first attempt".
7. Not Windows-only: the natural `getaddrinfo('localhost')` family order on the (macOS) review host is IPv6-first as well.
8. CI fully green at head (CI OK 2026-09-03: Ruff, gitleaks, Ubuntu/Windows/macOS builds; CodeRabbit: no actionable comments) and the branch merge-trees cleanly onto develop `9a5fc5c8` despite being 79 behind — the only merge gate is the human review.

**One-line recommendation:** Ask mayu99 to answer joshuadarron's (a)-or-(b) question — (b) is a two-line body edit (`Fixes`→`Refs` + a scoping sentence) that unblocks re-review immediately, while (a) additionally delivers #994's first-attempt contract (and, if chosen, needs the co-located doc touch for the new public method in the same change); the code as it stands is verified correct and needs no rework either way.

## 8. Coordination notes

- **Focused-run gotcha for the CPU pair:** running `pytest packages/ai/tests/ai/web/test_server.py` in isolation yields 16 setup errors from `packages/ai/tests/conftest.py:24` (`ai.account` inject-if-absent collision) — pre-existing, masked by full-suite collection order. Preload the real `ai.account` (my `preload_ai_account.py` plugin pattern in the session scratchpad) or run an `ai/account` test file first. Worth knowing before anyone attributes those errors to their own PR.
- **No file overlap with the CPU pair:** #1708 and #2003 each touch only `packages/server/engine-lib/rocketlib-python/lib/depends.py` — no intersection with #2005's files, nor with the `task_http` callers option (a) would edit. Incidentally, `depends.py` is the engine-bound module this review had to shim (it imports `engLib`); if their PRs change its import-time behavior, the ai test suite's mock-injection preamble (`_inject('depends', ...)`) is the seam that keeps these tests independent of it.
- **Conventions:** commits use conventional style (`fix:`, `docs:`); base is `develop`; Python single quotes respected; Ruff green in CI — no repo-convention violations.
- **Separable follow-up candidate (pre-existing, repo-wide):** unbracketed IPv6 literal host in `RR_BASE_URL` formatting (`server.py` L487/L793) — reachable only with an operator-set IPv6 literal host; if the team adopts review-option (a), `get_local_uri()`'s `[::1]` bracketing covers the loopback slice of the same concern.
- No GitHub writes performed; all evidence gathered read-only via `gh` plus local execution in the isolated worktree/venv.
