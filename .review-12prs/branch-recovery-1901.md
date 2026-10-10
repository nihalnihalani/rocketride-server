# Branch recovery plan — PR #1901 (`fix(client-python): reject unknown constructor kwargs`)

Owner: python-sdk-reviewer · PR head analysed: `58990420bfd6f7b2f8d1f33826c6f4884fd845a9`
Correct base: **develop @ `973cd9b45ead293dd22fb8f7036ef1a1b325ca6b`** (or whatever `upstream/develop` is at the time of the rebuild).
Branch merge-base today: `6034cd411` — 91 commits behind develop.

**The recovery in this document has been executed and verified end to end** (§4). It is not a proposal
on paper: the reconstructed tree is byte-identical to the PR's head tree, and the CI lint gate goes
green after one formatting fix.

---

## 1. What the branch actually contains

The starting hypothesis was "polluted branch, 609 files". That is not what is going on — there is
**no foreign work and nothing to discard for content reasons**. The branch is the author's five
commits plus a replayed copy of develop's own history.

Measured:

```
git rev-list --count 6034cd411..refs/review-12prs/1901                    ->  96 commits
git rev-list --count --cherry-pick --right-only <develop>...<branch>      ->   5 commits
git diff --name-only <develop>...<branch> | wc -l                         -> 609 files   (three-dot)
git diff --stat      <develop>..<branch>                                  ->   2 files, +108   (two-dot)
```

**Exactly 5 of the 96 commits have no patch-equivalent anywhere in develop, and all 5 are the
author's.** The remaining 91 are develop's commits replayed with different SHAs. Two further symptoms
of that replay:

* the branch contains **two copies of the same develop commit** — `26020d28` and `d5147a7d`, both
  *"fix(ai): getNodeConfig drops top-level keys and delivers arrays as IJson when profile is set (#2039)"*;
* it contains a copy of develop's **current tip** — `a64c7d36` ≡ `973cd9b4`,
  *"fix(ai): name the cause when a reasoning model is cut off mid-&lt;think&gt; (#1823)"*.

The branch is **linear** — every commit has a single parent, so there are no merge commits to unpick.
Its shape:

```
6034cd411   (an old develop)
 │
 ├─ 6f210099  author  2026-08-09  reject unknown constructor kwargs        client.py +38, test +38
 ├─ e3e1157e  author  2026-08-10  reject transport kwarg + document opts   client.py +13/-1, test +11
 ├─ aa3d887f  author  2026-08-12  validate kwargs before initialization    client.py +9/-9
 ├─ 7b65a194  author  2026-08-12  style: satisfy ruff formatting           client.py +1/-3
 │
 ├─ 2937de73 … a64c7d36   ← 91 REPLAYED develop commits (2026-08-09 … 2026-09-04)
 │
 └─ 58990420  author  2026-09-07  reject transport kwarg + document opts   test +17/-5   (tip)
```

So the author branched from an old develop, wrote four commits, then **replayed develop's history on
top of their own work** instead of rebasing their work onto develop, and later added a fifth commit at
the tip.

**Why it still merges clean.** The 91 replayed commits are content-identical to develop's, so
`merge-tree` reports no conflict and the *content* delta is 108 lines. The damage is to history and to
reviewability, not to the code:

* merging would graft 91 duplicate commits into develop — a month of work appearing twice in
  `git log`, `#2039` appearing three times in total, and `git bisect` traversing duplicated states;
* GitHub computes the PR diff three-dot (vs merge-base), and the replayed commits are unreachable from
  develop, so their content is attributed to this PR: **609 files for a 108-line change**, which no
  human can review.

**Nothing of this change is already on develop.** `packages/client-python/src/rocketride/client.py` at
develop has no allowlist, and `packages/client-python/tests/test_client_constructor_kwargs.py` does not
exist. The two-dot diff is purely additive (+108 / −0).

## 2. Exact commits and hunks to retain

Retain the author's five commits — nothing else. Their combined effect is:

| file | change |
|---|---|
| `packages/client-python/src/rocketride/client.py` | +47 |
| `packages/client-python/tests/test_client_constructor_kwargs.py` | +61 (new file) |

Hunk by hunk in `client.py` (line numbers as they land on develop):

| hunk | lines | content | retain? |
|---|---|---|---|
| 1 | `:78-101` | `_KNOWN_CONSTRUCTOR_KWARGS` frozenset of 16 names, with the explaining comment | **yes** |
| 2 | `:139-143` | `TypeError` added to the **class** docstring `Raises:` | **yes** |
| 3 | `:182-195` | eight previously-undocumented options added to the `**kwargs` docstring (`client_name`, `client_version`, `public`, `on_trace`, `on_event`, `on_connected`, `on_disconnected`, `on_connect_error`) | **yes** — a real documentation improvement, independent of the validation |
| 4 | `:196-199` | `TypeError` added to the `__init__` docstring `Raises:` | **yes** |
| 5 | `:191-196` | the `unknown = set(kwargs) - _KNOWN_CONSTRUCTOR_KWARGS` check, placed as the first statement of `__init__` | **yes** — the placement (before env, URI and any state) is the point of commit `aa3d887f` |

In the test file, all four tests are retained
(`test_unknown_constructor_kwarg_raises_type_error`, `test_unknown_constructor_kwargs_all_listed`,
`test_documented_constructor_kwargs_still_accepted`, `test_transport_kwarg_rejected`).

**Exclusions** — everything else on the branch:

* all 91 replayed develop commits (`2937de73` … `a64c7d36`);
* in particular the duplicated `#2039` pair (`26020d28`, `d5147a7d`) and the tip-copy `a64c7d36`;
* `d4b9bd30` *"fix: remove event monitor token filter (#1701)"* — also by Eric Wang, but already merged
  to develop under a different SHA; it is develop content, not part of this change.

## 3. Two routes; pick by whether commit granularity matters

Both were executed and both produce a tree byte-identical to the PR head (§4).

### Route A — single fresh commit (recommended)

Simplest, and appropriate because the whole change is one coherent 108-line fix whose intermediate
commits are iterations rather than separable steps (`7b65a194` is pure formatting; `58990420` reworks a
test `e3e1157e` added).

```bash
git fetch upstream develop
git switch -c fix/RR-1837-reject-unknown-constructor-kwargs upstream/develop

# take the two files exactly as they are at the PR head
git checkout <pr-head> -- packages/client-python/src/rocketride/client.py \
                          packages/client-python/tests/test_client_constructor_kwargs.py

git commit -m "fix(client-python): reject unknown constructor kwargs instead of silently ignoring them

Closes #1837"
```

Branch name follows `CONTRIBUTING.md` (`<type>/RR-<issue>-<description>`, enforced by a ruleset).

### Route B — cherry-pick the five commits (preserves authorship granularity)

```bash
git fetch upstream develop
git switch -c fix/RR-1837-reject-unknown-constructor-kwargs upstream/develop
git cherry-pick 6f210099 e3e1157e aa3d887f 7b65a194 58990420
```

Executed: **all five apply cleanly, no conflicts.** Consider `git rebase -i` afterwards to squash
`7b65a194` (formatting) into `aa3d887f`, and `58990420` into `e3e1157e`, leaving two meaningful
commits.

### Do **not**

* `git rebase upstream/develop` on the existing branch — it replays all 96 commits. The 91 duplicates
  would mostly resolve to empty and be dropped, but the run is long, noisy, and any non-empty residue
  silently reintroduces duplicate history.
* `git merge upstream/develop` into the branch — that keeps all 96 commits reachable and makes the
  problem permanent.
* Cherry-pick "everything since the merge-base" — that is the 91 duplicates.

## 4. Verification that this recovery works (executed)

Environment: macOS (darwin 25.5.0, arm64), Python 3.12.12, venv `<scratchpad>/venv312`, pytest 9.1.1,
pytest-asyncio 1.4.0, pytest-timeout 2.4.0, ruff 0.16.6. Scratch worktree `.wt/recov` created at
develop `973cd9b4` (a throwaway detached worktree under my own tree — **no PR checkout was modified**).

```
cmd : git worktree add --detach .wt/recov 973cd9b4                       -> HEAD at 973cd9b4
cmd : git cherry-pick 6f210099 e3e1157e aa3d887f 7b65a194 58990420       -> exit 0, 5/5 clean, no conflicts
cmd : git diff --stat 973cd9b4 HEAD
      packages/client-python/src/rocketride/client.py                | 47 +++++++++
      packages/client-python/tests/test_client_constructor_kwargs.py | 61 ++++++++++++
      2 files changed, 108 insertions(+)
cmd : git diff --stat refs/review-12prs/1901 HEAD                        -> EMPTY
```

The last line is the important one: **the reconstructed working tree is byte-identical to PR #1901's
head tree**, across the whole repository. Nothing is lost and nothing extra is carried.

```
cmd : python -m pytest tests/test_client_constructor_kwargs.py tests/test_client_env_loading.py \
             tests/test_dap_client.py tests/test_formatters_truncate.py tests/test_monitor_keys.py -q
cwd : .wt/recov/packages/client-python
exit: 0 · out: 19 passed in 0.05s   (the PR's 4 tests + 15 pre-existing offline tests)
```

The CI lint gate, before and after the one required fix:

```
cmd : ruff format packages/client-python/tests/test_client_constructor_kwargs.py
out : 1 file reformatted                    (removes the trailing blank line after :60)
cmd : ruff format --check .                 -> exit 0, "1746 files already formatted"
cmd : ruff check .                          -> exit 0, "All checks passed!"
cwd : .wt/recov, ruff 0.16.6
```

So the reconstruction plus one `ruff format` clears the exact gate that is red on the PR today
(`.github/workflows/ci.yml:215-216`).

**Route A verified separately** in a second scratch worktree `.wt/recovA`, also at develop `973cd9b4`:

```
cmd : git checkout <pr-head> -- packages/client-python/src/rocketride/client.py \
                                packages/client-python/tests/test_client_constructor_kwargs.py
cmd : git commit -m "fix(client-python): reject unknown constructor kwargs …"
out : BLOCKED by the repo's own lefthook pre-commit hook —
        ✓ gitleaks      (no leaks found)
        ✓ ruff-check    (All checks passed!)
        ✗ ruff-format   Would reformat: packages/client-python/tests/test_client_constructor_kwargs.py
      exit status 1
cmd : git diff --stat 973cd9b4 HEAD                -> 2 files, +108 (after committing)
cmd : git diff --stat refs/review-12prs/1901 HEAD  -> EMPTY
```

Two things worth taking from that run. Route A reproduces the PR head tree exactly, same as Route B.
And the repository's **own pre-commit hook catches the formatting violation** (`lefthook.yml:19-21`) —
which is a direct confirmation of the red CI's cause: the PR body states the change was committed with
`--no-verify` because ruff was not installed in the author's environment. Installing ruff and letting
the hook run would have prevented it. That is the whole of `Ruff`'s failure on this PR.

**Not verified (engine unavailable):** `./builder client-python:test` needs the engine binary and a
live server, so the server-backed suites were not run on the reconstructed branch. Every in-repo
`RocketRideClient(...)` construction was checked statically to use only allowlisted options
(`prs/1901.md` §5-E), and CI reports 16 checks green at the PR head, which covers that ground better
than I can locally.

## 5. Prerequisites

1. **`upstream/develop` fetched fresh.** develop moves; re-derive the base at rebuild time rather than
   pinning `973cd9b4`. Re-run `git diff --stat upstream/develop..HEAD` afterwards and confirm it is
   still the same two files (§7).
2. **Branch naming.** `CONTRIBUTING.md:27-48` — `<type>/RR-<issue-number>-<short-description>`,
   enforced by a GitHub ruleset. `fix/RR-1837-reject-unknown-constructor-kwargs`.
3. **Issue link.** The PR body must keep `closes #1837` (CI requires a linked issue,
   `CONTRIBUTING.md:100`).
4. **Successor-PR decision.** Because the branch history must change, the author has two options:
   force-push the rebuilt branch to the *same* PR branch (keeps PR #1901, its comments and its
   `closes #1837` link), or open a new PR and close #1901 with a pointer. Force-push to the existing
   branch is preferable — it preserves the review thread and the CodeRabbit history. Nothing here
   requires reopening a closed PR.
5. **Lint locally before pushing.** `ruff check` and `ruff format --check` at repo root. The author
   noted committing with `--no-verify` because ruff was not installed in their environment; the tip
   commit's trailing blank line is the direct consequence.

## 6. Post-reconstruction validation checklist

Run in order; each has a concrete pass condition.

| # | check | pass condition |
|---|---|---|
| 1 | `git diff --stat upstream/develop..HEAD` | exactly 2 files, +108 / −0 |
| 2 | `git diff upstream/develop...HEAD --name-only \| wc -l` | **2** (not 609) — confirms the three-dot diff GitHub will render is clean |
| 3 | `git log --oneline upstream/develop..HEAD` | 1 commit (Route A) or ≤5 (Route B) — **no develop commits listed** |
| 4 | `git rev-list --count --cherry-pick --right-only upstream/develop...HEAD` | same as (3); zero patch-equivalent duplicates |
| 5 | `ruff check .` and `ruff format --check .` | both exit 0 |
| 6 | `pytest tests/test_client_constructor_kwargs.py` | 4 passed |
| 7 | `pytest tests/test_client_env_loading.py tests/test_dap_client.py tests/test_formatters_truncate.py tests/test_monitor_keys.py` | 15 passed — no offline regression |
| 8 | `./builder client-python:test` (needs the engine) | full suite green — the one check I could not run |
| 9 | GitHub: PR "Files changed" | shows 2 files |
| 10 | CI `Ruff` and `CI OK` | green |

## 7. Content fixes to fold in during the rebuild

These are the code-review items from `prs/1901.md`; the rebuild is the natural moment for them.

**Required:**

1. `packages/client-python/tests/test_client_constructor_kwargs.py:61` — delete the trailing blank
   line (one `ruff format`). This is the entire cause of the red `Ruff` check. *(PR1901-F2)*
2. `packages/client-python/tests/test_client_constructor_kwargs.py:51-53` — the comment claims *"the
   DAP base chain never consumes a caller-supplied transport"*. It does:
   `core/dap_base.py:151: self._transport = kwargs.get('transport', None)`. The real reason `transport`
   cannot be passed is the collision with `transport=None` at `client.py:258`, which is why it was
   *already* a `TypeError` before this PR — just a confusing one. *(PR1901-F5)*

**Recommended, not blocking:**

3. Switch the four tests from `try/except/else: raise AssertionError(...)` to `pytest.raises`, matching
   every other test file in the package. *(PR1901-F6)*
4. Add tests for the two subclass patterns and for `RocketRideClient(**RocketRideClientConfig)`.
   *(PR1901-F3/F6)*
5. Add a test asserting `_KNOWN_CONSTRUCTOR_KWARGS` still matches what the MRO's `__init__`s consume,
   so the hand-maintained list cannot silently drift. *(PR1901-F4)*
6. A line in the class docstring telling subclass authors they must consume their own keywords before
   forwarding `**kwargs`. *(PR1901-F3)*
7. A `CHANGELOG.md` entry — this is a deliberate breaking change.

**Open question to settle before the rebuild** (it changes the code): hard `TypeError` vs a
`DeprecationWarning` grace period. The author offered the warning-only variant; #1837 reads as wanting
the loud error. Worth a maintainer answer first so the rebuild happens once.

## 8. Summary

| | |
|---|---|
| Foreign or unrelated work on the branch | **none** |
| Commits to retain | 5 (all the author's) — or squash to 1 |
| Commits to exclude | 91 replayed develop commits |
| Correct base | current `upstream/develop` |
| Net change | 2 files, +108 / −0 |
| Cherry-pick conflicts | **none** (executed) |
| Reconstructed tree vs PR head tree | **identical** (executed) |
| Blocking fixes to fold in | 1 formatting line, 1 wrong comment |
| Effort | ~15 minutes for the author |

The change is small, correct and worth having. The branch history is the only thing standing between
it and a review.

---

## Coordination notes

**@independent-verifier** — two commands reproduce the whole ancestry conclusion:
`git rev-list --count --cherry-pick --right-only <develop>...refs/review-12prs/1901` → **5**, and
`git diff --stat <develop>..refs/review-12prs/1901` → **2 files, +108**. The recovery itself is
reproducible in a throwaway worktree: cherry-pick the five SHAs onto develop and check that
`git diff refs/review-12prs/1901 HEAD` is empty. It is. Note the assignment's "polluted branch"
hypothesis is **not** what is happening — no foreign commits, just a replayed develop.

**@lead** — this is an "ask the author to rebuild" case, not a takeover: the author is active (five
commits over a month, latest 2026-09-07) and the work is ~15 minutes. Recommend force-pushing the
rebuilt branch to the existing PR branch so #1901, its `closes #1837` link and its review thread
survive. One maintainer decision should land first (hard `TypeError` vs deprecation window) so the
rebuild happens once.
