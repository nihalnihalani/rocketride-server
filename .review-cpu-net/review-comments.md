# Published PR comments (exact bodies) — see publication.md for URLs/SHAs

## PR #1708

<!-- rocketride-production-review:pr-1708 -->

**Recommendation: close in favour of #2003, once two pieces transfer across.** At head `1bf77b15` the `--extra-index-url .../whl/cpu` line cannot beat the exact `torch==2.10.0+cu128` / `torchvision==0.25.0+cu128` pins in [ai/common/torch/requirements.txt](https://github.com/rocketride-org/rocketride-server/blob/1bf77b153b046a265220409b83b8a098b9cafbf6/packages/ai/src/ai/common/torch/requirements.txt): replaying the CPU-mode compile input from [`_combine_requirements`](https://github.com/rocketride-org/rocketride-server/blob/1bf77b153b046a265220409b83b8a098b9cafbf6/packages/server/engine-lib/rocketlib-python/lib/depends.py#L707-L723) resolves a pin set byte-identical to flag-off — `+cu128`, 15 `nvidia-*`, triton, both ways — exiting 0 with only the emitted index list changed.

@kwit75, your own #1697 comment is what identified that pin as the root cause; this PR's design predates it, and the cited 119/13 → 105/0 run compiled the four nodes without that common pin file *and* manually pinned `+cpu`, an override step this mechanism never performs. Overrides are what beat an exact `==` local-version pin, which is #2003's approach.

Two pieces here shouldn't be lost with the PR:

- The [ONNX excludes flip](https://github.com/rocketride-org/rocketride-server/blob/1bf77b153b046a265220409b83b8a098b9cafbf6/packages/server/engine-lib/rocketlib-python/lib/depends.py#L834-L839) — #2003 leaves ONNX alone. Caveat on transfer: in Linux CPU mode it drops `onnxruntime-gpu` but cannot add the plain runtime (that line is Darwin-marked, and gliner 0.2.29 no longer requires ORT), so anonymize dry-runs with no ORT at all; pair it with a functional check.
- The normalised-boolean cache seed from commit `1bf77b15` ([L673](https://github.com/rocketride-org/rocketride-server/blob/1bf77b153b046a265220409b83b8a098b9cafbf6/packages/server/engine-lib/rocketlib-python/lib/depends.py#L673)) — #2003 hashes the raw env value.

For reviewers: asclearuc's blocking point 1 (cache key) *is* fixed at this head — that review was submitted against `ae0b3f0`, before this commit. Point 2 (testability, tests) stands: `from engLib import ...` is still at [L52](https://github.com/rocketride-org/rocketride-server/blob/1bf77b153b046a265220409b83b8a098b9cafbf6/packages/server/engine-lib/rocketlib-python/lib/depends.py#L52).

Validation is resolver-level (uv 0.11.25 cross-resolves, linux/cp312 and darwin-arm64); no install or functional run. Darwin with the flag set resolves fine (exit 0, plain wheels).

Next step: settle where the excludes flip lands on #2003.

## PR #2003

<!-- rocketride-production-review:pr-2003 -->

**Keep this as the vehicle for #1697:** at head `880f743f` it is the pair's only mechanism that strips CUDA against the in-tree pins: on linux/cp312, CPU mode gives `torch==2.10.0+cpu` / `torchvision==0.25.0+cpu`, zero `nvidia-*`, no triton. The derived overrides, not the extra index, beat the exact `+cu128` pins; #1708's index-only approach cannot.

@KESHAV8087, that is a vehicle choice, not a merge verdict. Before merge:

- **Darwin breaks.** The text-level pin scan ([L376-L388](https://github.com/rocketride-org/rocketride-server/blob/880f743f95869a959d557da71f79f60e83a0d68f/packages/server/engine-lib/rocketlib-python/lib/depends.py#L376-L388)) matches the non-Darwin `+cu128` lines on macOS, writing marker-less `+cpu` overrides; no macOS `+cpu` wheels exist, so compilation fails and `depends()` — called at engine import (`rocketlib/types.py:31`) — raises: startup breaks on any Mac with the flag set. Gate the helpers off on Darwin; don't preserve source markers as the open suggestion proposes — verified, a marker-false override makes uv drop the requirement entirely: Darwin resolves empty, exit 0, torch gone.
- **Rebase.** One of three conflicts against develop [`9a5fc5c8`](https://github.com/rocketride-org/rocketride-server/commit/9a5fc5c8c019e8f5c9da2c6239a04b9ff3bf78a6) is pure em-dash→hyphen churn (including the user-visible `'Waiting — {detail}'` string) hitting develop's satisfied-verdict cache: drop it, keep develop's side, then fold CPU mode into `_verdict_key` and bump `_VERDICT_SCHEMA`.
- **Hash the parsed boolean**, not the raw env value ([L738](https://github.com/rocketride-org/rocketride-server/blob/880f743f95869a959d557da71f79f60e83a0d68f/packages/server/engine-lib/rocketlib-python/lib/depends.py#L738)) — `1`/`true`/`yes`/`" 1 "` are four cache keys.
- **Tests and an env-var doc** under `packages/server/docs/`. CI has never run here — no Ruff, no build at either commit; ruff 0.16.5 (CI's pin) passes on the head blob locally, but that is not CI.

ONNX stays untouched by design (`onnxruntime-gpu` still resolves in CPU mode): fine for the torch contract, short of #1697's ask, which #1708's excludes flip covers if transferred. All CPU evidence here is resolver-level (uv 0.11.25); #1697's functional run of the four nodes still gates rollout.

## PR #2005

<!-- rocketride-production-review:pr-2005 -->

**The code is sound at head `e8379b59`; what is left is a scoping choice, not rework.** [`get_port()`](https://github.com/rocketride-org/rocketride-server/blob/e8379b596f4bf21d17a059c927dc133dd6c96a86/packages/ai/src/ai/web/server.py#L788-L835) does what it claims: the full module ran 16/16 and `TestGetPort` 3/3 with real IPv6 loopback available (no skips), `test_dual_stack_prefers_ipv4` genuinely fails against the merge-base implementation, and a 23-case run over degenerate states (closed socket, `AF_UNIX`, missing/empty containers, cached and configured ports, `RR_BASE_URL` semantics) came back clean. CI is green at this head, and the branch merge-trees cleanly onto develop.

@mayu99, the gap is between two different claims. This delivers "`get_port()` returns the IPv4 port". #994's stated expectation is "connects on the first attempt, regardless of which address family `getaddrinfo` returns first", and port selection cannot control client-side `localhost` resolution. All four callers still build `f'http://localhost:{port}'` — [task_cancel L28](https://github.com/rocketride-org/rocketride-server/blob/e8379b596f4bf21d17a059c927dc133dd6c96a86/packages/ai/src/ai/modules/task_http/task_cancel.py#L28), [task_status L31](https://github.com/rocketride-org/rocketride-server/blob/e8379b596f4bf21d17a059c927dc133dd6c96a86/packages/ai/src/ai/modules/task_http/task_status.py#L31), [task_data L516](https://github.com/rocketride-org/rocketride-server/blob/e8379b596f4bf21d17a059c927dc133dd6c96a86/packages/ai/src/ai/modules/task_http/task_data.py#L516), [task_exec L69](https://github.com/rocketride-org/rocketride-server/blob/e8379b596f4bf21d17a059c927dc133dd6c96a86/packages/ai/src/ai/modules/task_http/task_exec.py#L69) — and against a real IPv4-only listener under an IPv6-first resolver, `asyncio.open_connection('localhost', P)` still makes two attempts: `('::1', P)` refused, then `('127.0.0.1', P)` ok. Not Windows-only; the macOS host used for that experiment resolves `localhost` IPv6-first natively too.

joshuadarron's CHANGES_REQUESTED was submitted against this exact commit and neither offered resolution is present yet, so it is current:

- **(b)** body edit `Fixes #994` → `Refs #994` plus one scoping sentence, and a reply — unblocks re-review immediately, no code change.
- **(a)** `get_local_uri()` plus the four one-line caller edits — delivers #994's contract; a new public method also needs its co-located doc in the same change.

One limit worth stating: the body's full-suite 1557 → 1560 figure is engine-bound and was not re-runnable, so it is verified at module level only (13 → 16, delta exactly the three new tests).

Next step: say which option you prefer.
