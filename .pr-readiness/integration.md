# Integration check — #1607 + #1581 + #1612 together

Author: sdk-implementation-engineer. **The integration worktree was never pushed** and is a
throwaway; only the three candidate commits are deliverables.

Worktree: `<agent-wt>/wt/integration`, branch `integration-check`, base develop `f9a25cbbd`.
Final integration commit (throwaway): `448e90926`.

## Proposed merge order

**#1607 → #1581 → #1612**

Reasoning:

1. **#1607 first** — it is the only candidate that does not touch `_add_connection_args`, so
   it lands on develop with zero interference and gives the other two a stable base.
2. **#1581 second** — it introduces `_add_connection_args(..., *, json_arg=True)`.
3. **#1612 last** — it introduces the **byte-identical** `json_arg` change, so git
   auto-resolves that hunk (verified: the integrated `main.py` has exactly one
   `_add_connection_args` definition and git reported no conflict there). It also carries the
   `docs/README-clients.md` modify/delete relocation, which is the most fragile resolution and
   benefits from being applied against the most settled tree.

Order is a preference, not a constraint: any permutation produces the same six conflicting
files with the same additive resolutions.

## What actually happened

| Step | Merge | Conflicts |
| --- | --- | --- |
| 1 | `f9a25cbbd` + `b2d6d5bda` (#1607) | **none** — clean merge |
| 2 | + `8e7ef7230` (#1581) | 6 files (all additive) |
| 3 | + `1d16eed5f` (#1612) | 6 files (all additive) |

The six are always the same: `CHANGELOG.md`, `docs/README-python-client.md`,
`packages/client-python/docs/index.md`,
`packages/client-python/src/rocketride/cli/commands/__init__.py`,
`packages/client-python/src/rocketride/cli/main.py`,
`packages/docs/content-static/cli.mdx`. Every hunk is "keep both", except one that needs a
human:

> **`packages/docs/content-static/cli.mdx` intro blockquote needs a manual count bump on each
> land.** It reads "the Python CLI includes **three** additional commands (`events`, `list`,
> `diff`)". Each landing PR rewrites the same sentence, so the merge produces two competing
> sentences rather than a mergeable list. The count must go three → four → five and the list
> must accumulate. Final integrated text:
> `> includes five additional commands (`events`, `list`, `diff`, `eval`, `otel`) not present in TypeScript.`
> **Whoever lands #2 and #3 must fix this by hand; a mechanical "keep both" leaves a
> duplicated sentence.**

`CHANGELOG.md`: the three `client-python` lines were ordered by ascending PR number
(1581, 1607, 1612), matching the convention visible elsewhere in the file.

## Verification of the combined tree

### No command silently removed / registered twice / given another's args

```
commands (unique):  ['init','login','list','start','stop','upload','validate','diff','eval','otel','store','app','deploy']
dispatch branches:  ['app','deploy','diff','eval','init','list','login','otel','start','stop','store','upload','validate']
commands.__all__:   ['run_app','run_deploy','run_diff','run_eval','run_init','run_list',
                     'run_login','run_otel','run_start','run_stop','run_store','run_upload','run_validate']
```

- 13 subparsers, all names unique (`len(names) == len(set(names))` asserted).
- Every subparser name has exactly one `_dispatch` branch, and vice versa.
- `_add_connection_args` appears **once**, with the `json_arg` keyword.
- `rocketride <cmd> --help` exits 0 for all 13.

Per-command argument isolation (from `--help` + parsed namespaces):

| Command | must have | must NOT have | result |
| --- | --- | --- | --- |
| `validate` | `--source`, `--json [FILE]` | `--git`, `--markdown`, `--junit`, `--endpoint`, `--case` | ok |
| `diff` | `--git`, `--markdown`, `--include-layout`, `--exit-zero` | `--uri`, `--apikey`, `--token`, `--source`, `--junit`, `--endpoint`, `--case` | ok — namespace is exactly `['command','exit_zero','git','include_layout','json','markdown','paths']`. (The bare `--help` grep reports `--uri/--apikey` as "present"; that is a **false positive** — the only occurrence is inside the description sentence "…so it takes no `--uri`/`--apikey` arguments".) |
| `eval` | `--case`, `--fail-fast`, `--junit`, `--uri`, `--apikey` | `--git`, `--markdown`, `--source`, `--endpoint`, `--json [FILE]` | ok |
| `otel` | `--endpoint`, `--protocol`, `--service-name`, `--headers`, `--insecure`, `--include-content`, `--no-metrics`, `--trace-level`, `--uri`, `--apikey` | `--git`, `--markdown`, `--junit`, `--case`, `--source`, `--json` | ok |

`--json` semantics survive side by side:

| Invocation | Expected | Got |
| --- | --- | --- |
| `validate a.pipe --json` | `args.json == '-'` | ✓ |
| `validate a.pipe --json=out.json` | `args.json == 'out.json'` | ✓ |
| `eval x.eval.json --json` | `args.json is True` | ✓ |
| `eval x.eval.json --json=out.json` | rejected (exit 2) | ✓ |
| `otel --json` | rejected (exit 2) — `otel` has no `--json` | ✓ |

### Public imports

```python
import rocketride, rocketride.pipediff, rocketride.evals, rocketride.otelbridge
from rocketride.cli.commands import run_diff, run_eval, run_otel, run_validate
from rocketride.cli.main import setup_parser, _dispatch
```
All succeed. `py_compile` clean on `cli/main.py` and `cli/commands/__init__.py`.

### Combined test suites

`python -m pytest tests/ -q --timeout=120 --ignore=RocketRideClient_test.py --ignore=test_cli_integration.py`
→ **524 passed, 21 errors**, 2.41 s.

`524 = 70 (develop baseline) + 123 (#1607) + 197 (#1581) + 134 (#1612)` — exact, so no test
was lost, duplicated, or shadowed when the three landed together. The 21 errors are the same
engine-bound `ConnectionError` fixtures as on plain develop.

`ruff check` → `All checks passed!`; `ruff format --check` → `122 files already formatted`.

### Package contents and dependency metadata

`python -m build` on the integrated tree:

- wheel ships `rocketride/pipediff/` (5 modules), `rocketride/evals/` (6 modules +
  `templates/__init__.py` + `templates/judge-default.pipe`), `rocketride/otelbridge/`
  (5 modules), and `cli/commands/{diff,eval,otel,validate,app,auth,deploy,store,tasks}.py`.
- sdist carries the same (5 / 9 / 5 files).
- `Provides-Extra: dev, otel, test` — the `otel` extra survives with
  `opentelemetry-sdk>=1.27.0` and `opentelemetry-exporter-otlp-proto-http>=1.27.0`.
- `[console_scripts] rocketride = rocketride.cli.main:main` — single entry point.
- `[tool.setuptools.package-data]` carries both `rocketride = ["py.typed"]` (develop) and
  `"rocketride.evals.templates" = ["*.pipe"]` (#1581).

### Docs coherence

- `docs/README-python-client.md`: `## CLI` → `### validate` → `### Semantic pipeline diff
  (rocketride diff)` → `### rocketride eval` → `### OpenTelemetry export (rocketride otel)` →
  `## Configuration`. One CLI command block listing `validate`, `store dir /`, `diff`, `eval`,
  `otel`.
- `packages/docs/content-static/cli.mdx`: commands table has `validate`, `eval`, `otel`,
  `store`, `diff` each once; sections `### validate`, `### eval`, `### otel`, `### store`,
  `### diff` each once.
- `CHANGELOG.md` Unreleased → Added: `cli (#1573)`, then `client-python` eval (#1581), diff
  (#1607), otel (#1612).
- `.github/actions/` holds both `validate-pipes` (develop) and `pipe-diff` (#1607).
- Repo-relative doc links added by the three PRs all resolve: `CONTRIBUTING.md`, `LICENSE`,
  `examples/pipe-diff-example.md`, `examples/rag-pipeline.eval.json`,
  `packages/client-python/docs/otel-bridge.md`, `.github/actions/validate-pipes`,
  `.github/actions/pipe-diff`, `docs/develop/README-clients.md`.
  **One dead link was found and fixed** in the #1612 candidate — see below.
- `builder docs:build` was **not run**: it needs a full `pnpm install` plus the engine build
  chain, and `node_modules/` is absent in these worktrees. The checks above substitute for it;
  the lead should still let CI's docs job be the final word.

### Bug found by the integration check and fixed upstream in the candidate

`packages/client-python/docs/otel-bridge.md` (#1612) linked its "Client libraries overview" at
`blob/develop/docs/README-clients.md`, a file develop deleted. Fixed in the #1612 candidate by
re-pointing at `blob/develop/docs/develop/README-clients.md`, and the candidate was amended
(`8edb7df31` → `1d16eed5f`); the integration merge was then redone against the amended commit.
Repo-wide scan for the old path now returns 0 hits.

## Follow-up sync needed after the first lands

Once the first of the three merges into develop, the other two become behind again and will
conflict on the same six files. For each remaining PR:

1. `git fetch upstream && git merge upstream/develop` (merge, never rebase — the approvals are
   anchored on the head commits).
2. Resolve the six files additively:
   - `CHANGELOG.md` — keep both lines, ascending PR number within the `client-python` scope.
   - `docs/README-python-client.md`, `packages/client-python/docs/index.md` — keep both
     command lines in the fenced block; keep both prose sections; `validate` stays first.
   - `packages/docs/content-static/cli.mdx` — keep both table rows and both sections, and
     **hand-edit the intro blockquote's count and command list** (three → four → five).
   - `cli/commands/__init__.py` — keep both imports and both `__all__` entries, alphabetical.
   - `cli/main.py` — keep both docstring lines, both parser blocks (each after `validate`),
     both `_dispatch` branches, and the single `json_arg` form of `_add_connection_args`.
3. Re-run: `pytest tests/ --ignore=RocketRideClient_test.py --ignore=test_cli_integration.py`,
   `ruff check`, `ruff format --check`, `rocketride --help`, `rocketride <cmd> --help`.
4. Re-check `git merge-tree --write-tree <candidate> upstream/develop` right before pushing —
   develop moved once already during this run.

Also note for whoever lands #1612: `docs/develop/README-clients.md` is a **new-on-develop**
file, so if develop restructures the docs tree again the relocation must be re-checked rather
than assumed.
