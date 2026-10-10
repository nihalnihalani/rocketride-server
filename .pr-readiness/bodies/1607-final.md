## Summary

- **`rocketride diff`** — a semantic diff for `.pipe` files. Matches components by `id` and reports added/removed nodes, `provider` changes, a deep `config` diff as dotted field paths (`config.parameters.model: gpt-4 → gpt-4o`), and edge (wiring) changes reconstructed from each component's `input[]` data lanes **and** `control[]` agent-orchestration lanes. Canvas layout — every node's `ui` block and the top-level `viewport` — collapses to one `layout changed` line by default, so a one-line model swap stops surfacing as 70 lines of `x`/`y` deltas. `--include-layout` opts the churn back in and enumerates it as `ui.*` and `viewport.*` field changes.
- **Two input modes, three outputs, CI-shaped exit codes.** Two files, or `--git <ref> <file.pipe>` against a git ref via `git show`. Human (grouped, colored, `NO_COLOR`/non-tty aware), `--json` (one stable sorted document), `--markdown` (PR-comment-safe). Exit `0` no changes · `1` changes · `2` usage/parse/git error; `--exit-zero` for non-gating runs. `diff` is the only subcommand that never connects to an engine, so it takes no `--uri`/`--apikey`/`--token`.
- **`.github/actions/pipe-diff`** — a composite action that finds every changed `.pipe` in a PR, diffs each against the base, and maintains one sticky comment, with the same report always written to the job summary.

## Type

Feature (Python SDK/CLI + one composite action + docs). No engine, server, or existing-workflow changes; no new dependencies.

**Same change, two views** — a diff that swaps one model, adds a node, rewires an edge, and nudges every canvas position:

<table>
<tr><th>Raw <code>diff -u</code> (today)</th><th><code>rocketride diff</code> (this PR)</th></tr>
<tr><td><pre>71 changed lines, mostly:
-  "x": 20,
-  "y": 200
+  "x": 60,
+  "y": 215
-  "x": 240,
+  "x": 280,
...</pre></td><td><pre>Pipeline diff: 1 node added, 1 node
changed, 1 edge added, layout changed

Nodes
  + rerank_1 (rerank_cohere)

Edges
  + qdrant_1 --documents--> rerank_1

Config
  llm_openai_1
    + config.parameters.model = gpt-4o

Layout: changed (ui/viewport)</pre></td></tr>
</table>

This is the review half of "pipelines as code": **validate** proves a pipe is well-formed, **eval** proves it behaves, and **diff** makes the change itself reviewable.

## Sync with develop (2026-09-04)

Rebased onto `upstream/develop` @ `65a2e133` (the branch was 170 commits behind, merge-base 2026-07-14). **No conflicts** — the four original commits (`60c12d9d`, `dac850c2`, `7ff4daa3`, `f4c3002d`) replayed cleanly. develop's `aa9c71b8` stdout/stderr `reconfigure(errors='replace')` in `main()` and this PR's `setup_parser`/`run()` hunks are non-overlapping, and it incidentally protects the reporters' `→` glyph on Windows consoles. develop has moved six commits since (`0788b9c4` at the time of writing); none touch this PR's files and `git merge-tree` against it is still clean, so the branch is left on `65a2e133` rather than re-rebased for no reason.

Nothing was dropped. Seven fixup commits were added on top, in order:

| SHA | What |
| --- | --- |
| `4073c477` | `fix(cli)`: pipediff input validation, reporter escaping, and the `--include-layout` viewport gap (CodeRabbit round 1, July) |
| `10ae56e7` | `fix(ci)`: pipe-diff action — job summary, fork-PR 403 handling, Markdown escaping, deletion semantics, `install-from` (round 1) |
| `9a28eed1` | `docs`: viewport in the documented JSON schema, external `uses:` reference, `install-from`, fork-PR note, CHANGELOG (round 1) |
| `4f995ad9` | `fix(pipediff)`: collision-safe backtick delimiters in the action's Markdown, duplicate component ids rejected, exit-code-based git ref checks, layout `null`-vs-`{}` normalization, SHA-pinned `uses:` in the doc snippets, `install-from` documented as executable source (round 2) |
| `295e6c3d` | `fix(pipediff)`: percent-encoded `::error` annotations (workflow-command injection via a PR-controlled filename), falsy layout values (`false`/`0`/`""`) no longer folded into `{}`, docs install the client from a pinned commit instead of a release that lacks `diff` (round 3) |
| `77d212e7` | `fix(pipediff)`: `_json_equal` compares with JSON typing, so `false`↔`0` / `true`↔`1` flips are reported instead of collapsing under Python's `False == 0` (round 4) |
| `6f919975` | `fix(ci)`: the base-fetch failure path builds a marker-carrying body and calls `write_job_summary` before `exit 1`, so the one path that skipped the summary no longer does (round 4, outside-diff note) |

**CodeRabbit: four rounds, 23 inline findings (12 + 7 + 3 + 1), all addressed in code and every thread resolved** — 27 threads in total, the other four being my own July self-review notes. The two "outside diff range" notes from the review bodies (the `run()` docstring exit-code contract → `4073c477`; the base-fetch failure path writing no job summary → `6f919975`) are answered as PR comments, since they are not inline threads. The behavioural fixes worth calling out:

- **`--include-layout` now does what `--help` and the docs said it did.** It only ever promoted per-node `ui` changes; a top-level `viewport`-only edit printed nothing and exited 0. `PipeDiff` gains `viewport_changes`, it counts toward `has_semantic_changes`, all three reporters render it, and the **documented `--json` schema changes**: a new top-level `viewport` array and a `summary.viewport_changes` count (updated in `cli.mdx` and `README-python-client.md`). Rounds 2–4 then closed three ways the layout flag could still lie: `null`-vs-`{}` set `layout_changed` with nothing to show, `false`/`0`/`""` were folded into `{}`, and `False == 0` hid boolean↔number flips.
- **Input validation.** `input`/`control` wire collections are validated before edge extraction — a non-list collection raised `TypeError`, an unhashable `from` blew up in `set.add`, and a wire missing `from` produced a silent `(None, None, id)` edge. All three are now exit-2 errors naming the component and wire index. Duplicate component `id`s are rejected too (a duplicate used to shadow the earlier node and hide every change to it). All 35 `.pipe` files in the repo pass the stricter check unchanged.
- **`UnicodeDecodeError` → `PipeDiffError`** on both the file-read and the git-output paths (it is a `ValueError`, not an `OSError`, so it escaped the library API as a traceback). `resolve_git_ref` now checks `rev-parse --verify` / `cat-file -e` exit codes instead of matching git's stderr text, so a ref whose name contains "does not exist in" is an exit-2 error rather than an all-added diff.
- **Output escaping.** The Markdown summary line's `version` and the caller-supplied `title` go through `_md_code`; the human renderer escapes CR/LF/ESC/C0 via `_term_safe` across ids, providers, lanes, paths and values.
- **The action writes a job summary on every path** — including the two that end in `exit 1` (undiffable `.pipe` file; unfetchable base commit) — treats deletions as semantic, chooses backtick delimiters per value so a PR-controlled path or stderr cannot close a code span or fence, percent-encodes file names and CLI stderr before they reach a `::error` annotation, and only updates a sticky comment authored by `github-actions[bot]`.

Two things a reviewer should weigh in on, both new in this sync:

- **`install-from` input.** Published `rocketride` is 1.3.0 and has no `diff`, so the action's verify step fails on every run until a release ships it — it could not be exercised at all. `install-from: ./packages/client-python` installs the CLI from a checkout instead of PyPI, which is how the action can be dogfooded before that release. I have **not** added a workflow that uses it; say the word if you want one under `.github/workflows/` in this PR.
- **Fork pull requests.** On a `pull_request` event from a fork the default `GITHUB_TOKEN` is read-only whatever `permissions:` says, so `issues.createComment` 403s — i.e. on exactly the PRs an open-source repo receives. The action emits a `core.warning` and leaves the full report in the job summary rather than failing the check; the README, `cli.mdx` and the PyPI README document the `comment: false` and `pull_request_target` trade-offs. The public docs also stopped telling external users `uses: ./.github/actions/pipe-diff` (a path that exists only inside this repo) and now show `rocketride-org/rocketride-server/.github/actions/pipe-diff@<ref>`.

**CI status.** Run [33893156188](https://github.com/rocketride-org/rocketride-server/actions/runs/33893156188) on the current head `6f919975` is fully green: **CI OK**, Build on Ubuntu 22.04 / Windows Server 2022 / macOS (ARM64) including the `Test` step, Shell API contract, Ruff, gitleaks and the CodeRabbit status. The three earlier fixup heads (`295e6c3d`, `77d212e7`) were green on their own runs too. This PR touches no `nodes/`, no `pnpm-lock.yaml`, no `services*.json` and no `client-typescript`, so those gates have no new inputs from it.

## Testing

- [x] Tests added or updated
- [x] Tested locally
- [x] `./builder test` passes — CI run [33893156188](https://github.com/rocketride-org/rocketride-server/actions/runs/33893156188) on the current head `6f919975`, `Test` step (`builder test --verbose --sequential`) green on all three Build OSes.

**121 unit tests pass** across the four pipediff files (was 79 at `f4c3002d`, before the sync; **42 added**), on Python 3.12 with the repo's root pytest config:

```
cd packages/client-python
python -m pytest tests/test_diff_cli.py tests/test_pipediff_engine.py \
  tests/test_pipediff_gitref.py tests/test_pipediff_reporters.py -q
# 121 passed  (test_diff_cli 22 · test_pipediff_engine 57 · test_pipediff_gitref 15 · test_pipediff_reporters 27)
```

Coverage: identical→empty; node add/remove; `provider` reported separately from `config`; nested-dict and list diffs with correct index paths; edge add/remove/rewire; `control[]` edges; version change; layout-only → non-semantic by default and semantic under `--include-layout`; **viewport-only → `viewport.*` paths and exit 1 only with the flag**; `null`/omitted/`false`/`0`/`""` layout values on both `viewport` and node `ui`; boolean↔number flips in viewport, ui and config; duplicate component ids; malformed pipes and malformed wires → `PipeDiffError`; invalid UTF-8 on both input paths; git resolver mocked for found / absent / bad-ref / ref-name-containing-git's-error-text / not-a-repo / git-missing / timeout / invalid-JSON / undecodable output, plus a real tmp-repo integration test; all three output modes, exit codes 0/1/2, `--json` stdout purity, `--exit-zero`; and Markdown/terminal injection payloads (version, title, ids, lanes, config values).

`ruff check` and `ruff format --check` over `pipediff/`, `cli/` and the four test files are clean (35 files already formatted). `gitleaks detect --log-opts upstream/develop..HEAD` scans the 11 branch commits and finds nothing.

The composite action was validated by parsing `action.yml` with PyYAML, running `bash -n` **and** `shellcheck -s bash` on all four extracted `run:` blocks (zero findings) and `node --check` on the async-wrapped `github-script` body, and then **executing the diff step end-to-end** against scratch git repositories in five scenarios (18 assertions): a semantic change (exit 0, `has-semantic-changes=true`, `changed-files=1`); no `.pipe` change (marker-only summary, `pipe-files-changed=false`); an unparsable `.pipe` at a path containing backticks (exit 0, `errored=true`, `::error file=` annotation); an unfetchable base commit (exit 1 **and** the summary carries the marker, the heading, the reason and the base SHA, with the `::error` annotation still on stdout); and the same failure with `GITHUB_STEP_SUMMARY` unset (exit 1, clean stderr). The `Post or update sticky PR comment` step (`actions/github-script`) cannot run outside a real runner; its 403 fallback and bot-author filter were checked by reading and `node --check` only.

## Checklist

- [x] Commit messages follow [conventional commits](https://www.conventionalcommits.org/)
- [x] No secrets or credentials included
- [ ] Wiki updated (if applicable)
- [x] Breaking changes documented (if applicable) — none; `diff` is a new subcommand and `pipediff` a new package.

## Notes for reviewers

- **One deliberate extension of the issue spec**: edges are read from `input[]` *and* `control[]`. `control[]` is how agent workflows wire agent→llm/tool/memory and it appears in most bundled examples; diffing only `input[]` would make the diff blind to agent reconfiguration. Documented in the engine docstrings and trivially revertible if you'd prefer input-only.
- `version` changes always count as semantic (their own line); `ui`/`viewport` are pure layout, hidden unless `--include-layout`.
- `.github/` is CODEOWNED by @kwit75 and `.github/actions/` does not exist on develop — whether an in-repo composite action is wanted at all is a maintainer call, and I am happy to split it into a follow-up or a separate repository. Related: `.github/dependabot.yml` scans `directory: "/"` for `github-actions`, which covers `.github/workflows` only, so the two SHA pins inside `action.yml` will not be maintained unless `/.github/actions/pipe-diff` is added there.
- **One CodeRabbit ask deliberately not taken**: the doc snippets still reference `pipe-diff@develop` while every third-party `uses:` in them is SHA-pinned. CodeRabbit asked for a commit SHA there too; I left the branch ref because the action does not exist on `develop` until this merges, and a pinned SHA from an unmerged branch would document a ref readers cannot use. CodeRabbit resolved the thread; if you would rather pin it, say which SHA.
- Four sibling PRs of mine (#1573 `validate`, #1581 `eval`, #1612 `otel`, #1613 README fix) insert adjacent lines in the same four files (`cli/main.py`, `cli/commands/__init__.py`, `cli.mdx`, `README-python-client.md`). Each merge forces a small re-rebase of the others and an update to the `cli.mdx` parity-note count; happy to follow whatever order you prefer.

## Linked Issue

Closes #1606

🤖 Generated with [Claude Code](https://claude.com/claude-code)

#Hire-Me-RocketRide

## Sync with develop (2026-09-10)

- `b2d6d5bd` merges `upstream/develop` @ `f9a25cbb` into the branch (merge commit; the approved head `6f919975` is its first parent, no history rewritten). Since the approval, develop rewrote the Python CLI (`RocketRideCLI`/`BaseCommand` → module-level `setup_parser()`/`_dispatch()` with `async run_<cmd>(args)` handlers) and merged #1573's `validate`, so a textual keep-both did not import.
- `diff` is ported to the new idiom with behavior held fixed: the `pipediff` engine, gitref, model and reporters are byte-identical to the approved head; `run_diff` keeps the documented exit codes (0 no semantic change or `--exit-zero`, 1 semantic changes, 2 errors on stderr), is dispatched directly rather than through develop's catch-all `run_cli_command`, and `--json` remains a plain format flag with pure stdout. `diff` is fully local and takes no connection options.
- Every accepted fix re-verified with its regression test at this head (type-sensitive JSON equality, layout-noise boundaries and `--include-layout`, output escaping, exit codes, composite-action input handling). Tests: 123 in this PR's files, 193 in the offline client-python package run (develop's 70 + 123), ruff clean, wheel ships `pipediff` and the console script; the `--git` path exercised against a real temporary repository.
- CI: [run 34488896663](https://github.com/rocketride-org/rocketride-server/actions/runs/34488896663) on `b2d6d5bd` — `CI OK` green (15 checks passed, 4 expected skips). Not verifiable outside CI: `test_cli_integration.py` (engine + live server).
- Shares six files with #1581 and #1612; proposed landing order #1607 → #1581 → #1612, and the `cli.mdx` intro count ("N additional commands") needs a one-word bump on each later land.
- **Round 3 `05278aae` (2026-09-11):** asclearuc approved with three inline notes; all addressed in one commit on top of the approved head. The sticky-comment step runs under `pull_request_target` as well as `pull_request`; the action now warns when the PR head is absent from the checkout (under `pull_request_target` the default checkout is the base branch, so the diff was base against itself). The action README's option 3, `cli.mdx` and `examples/pipe-diff-example.md` now say not to check out the PR head in a `pull_request_target` job (the action runs `python -m pip` and `git` inside the checkout, so PR-controlled files there are not inert) and describe the safe route for fork PRs — compute on `pull_request`, post from a `workflow_run` workflow; both `python` invocations in the action run with `-I` so the checkout can never shadow `pip`/`importlib`. The top-level `version` comparison uses `_json_equal` (with `1 → true` / `0 → false` tests), and `_md_cell` no longer doubles backslashes inside code spans (verified against cmark-gfm; Windows-path and regex tests). Tests: 104 pipediff tests pass; the two engine and two reporter regressions fail on the old code; YAML, `if:` expressions, `bash -n` and shellcheck are clean. CI: [run 34600631836](https://github.com/rocketride-org/rocketride-server/actions/runs/34600631836) on `05278aae` — `CI OK` green (16 checks passed, 4 expected skips).
- **Round 4 `c16b0eb9` (2026-09-11):** asclearuc approved with two notes. (1) Under `pull_request_target` with the PR head absent from the checkout, the run could post "No `.pipe` files changed" and overwrite a real sticky comment: the diff step now sets and exposes a `head-missing` output, the summary/body state that the run could not see the head (SHA named, README "Fork pull requests" referenced), the comment step is skipped in that case so it can never overwrite a real diff, and a moved base is labelled a base-branch diff; all other paths byte-identical (seven-state harness). (2) The backslash-before-pipe nit was investigated with cmark-gfm: the current `_md_cell` output is correct (n backslashes before a pipe keep the pipe escaped; the suggested change would add a visible backslash), so the code is unchanged, the docstring records the rule, and two tests pin the emitted bytes and the rendered round-trip. CI: [run 34619198961](https://github.com/rocketride-org/rocketride-server/actions/runs/34619198961) on `c16b0eb9` — `CI OK` green (16 checks passed, 4 expected skips).
