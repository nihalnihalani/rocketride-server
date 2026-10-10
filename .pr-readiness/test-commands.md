# TASK 2 — required-checks map

Source: `.github/workflows/*.yml` + `scripts/**`, all read at
**develop @ f9a25cbbd73f8feb9fbc99ea3aeb5bd241dafc1e**. GitHub's own branch-protection API
(`gh api repos/rocketride-org/rocketride-server/branches/develop/protection` and
`.../rules/branches/develop`) returned `404` / `[]` for this token — either the token lacks
admin-level visibility into protection settings, or protection is configured somewhere this API
view doesn't surface for a non-admin `repo`-scoped token. **I could not independently confirm the
GitHub-enforced required-check list via API; the map below is the codebase's own authoritative
statement of intent** (ci.yml's gatekeeper job + its inline comments), cross-checked against the
actual `statusCheckRollup` names seen on the 5 PRs' inventory JSON.

## The gate: `CI OK` (workflow `ci.yml`, job `ci-ok`)

Explicitly commented in-repo as *"the ONLY job to mark as 'Required' in branch protection. Aggregates
all CI results so skipped builds don't block PRs."* It `needs: [init, changes, build, helm-changes,
helm-lint, ruff-check, gitleaks, shell-contract]` and fails if any of those report `failure` or
`cancelled` (`always()` + a bash check of `needs.*.result`).

Two jobs are explicitly commented as **must never be added** to required checks because they don't
run on every PR: `container-scan` (non-PR only) and CodeQL (managed outside workflow files, repo
Settings → Code security). `check-externals` is separately, explicitly non-blocking
(`continue-on-error: true` on the PR lane) during a stated "stabilization" phase — it reports as a
check (`check-externals (PR)`, `check-externals (nightly)`) but a failure there does not fail `CI OK`.

## Per-area breakdown

### packages/client-python

- **pytest invocation**: not a bare `pytest`/`python -m pytest`. `packages/client-python/scripts/tasks.js`
  (`makeRunPytestAction`, task `client-python:run-pytest`) builds:
  `<ENGINE> -m pytest <packages/client-python>/tests -v --rootdir packages/client-python [--pytest passthrough]`
  via the shared `scripts/lib/pytest.js:runPytest()` helper (`args = ['-m', 'pytest', testsDir, ...extraArgs]`,
  executed as `execCommand(engine, args, ...)`). `ENGINE` is the **compiled server binary**
  (`dist/server/engine`), not a plain `python`/`python3` on PATH — so this call needs the
  engine build (**needs the engine binary — see "what needs the engine" below**). It also needs a
  **live server**: `client-python:run-pytest` runs inside a `bracket('py-test-server', ...)` that
  starts `dist/server/engine` listening on :5565 first (`ROCKETRIDE_URI=http://localhost:<port>`,
  `ROCKETRIDE_APIKEY=MYAPIKEY` in CI per `_build.yaml`'s `Test` step). Reached from CI via
  `./builder test --verbose --sequential` (`_build.yaml`, step "Test"), which is one call covering
  client-python + nodes + engine C++ tests together, run on all 3 platform matrix legs.
  Pytest ini config comes from root `pyproject.toml` `[tool.pytest.ini_options]` (client-python's
  own `pyproject.toml` has no `[tool.pytest.ini_options]` table, so pytest's config-file search
  continues up to the repo root): `testpaths=["tests"]`, `python_files=["test_*.py","*_test.py"]`,
  `addopts=["-v","-ra","--tb=short","--strict-markers"]`, `timeout=600`, markers `slow`/`integration`.
  Locally, `python -m pytest packages/client-python/tests` (the form in this repo's own
  CLAUDE.md "Common Commands") is an **approximation only** — it skips the engine-binary
  requirement and the CI marker/xdist defaults; it is not what CI actually runs.

- **ruff versions/config**: CI job `ruff-check` (ci.yml) pins the action's ruff version explicitly:
  `astral-sh/ruff-action@...` with `version: "0.16.5"` (inline comment: pinned deliberately so an
  upstream ruff release can't turn develop red on untouched files — see #1876). Runs repo-wide,
  no path filter: `ruff check` then `ruff format --check`. Config is the single root
  `pyproject.toml` `[tool.ruff]` (there is no client-python-specific ruff config — it inherits the
  repo-wide one): `line-length=120`, `target-version="py310"`, `force-exclude=true`,
  `[tool.ruff.format] quote-style="single"`, `[tool.ruff.lint] select=["E","F","Q","D"]` with a
  documented ignore list (`D100-D107,D200,D205,D301,D400,D401,E203,E402,E501`),
  `[tool.ruff.lint.flake8-quotes] inline-quotes="single"`, pydocstyle convention `pep257`. This
  is what CLAUDE.md means by "Python quotes: single quotes (enforced by ruff)." No engine needed —
  pure static analysis.

- **packaging**: `client-python:wheel-source` / `client-python:wheel-build` (referenced in
  `packages/client-python/scripts/tasks.js`, task list around line ~255-263) build the sdist/wheel;
  `_build.yaml`'s "Package" step (`${{ matrix.builder_cmd }} package --verbose`, only on
  `inputs.package == true`, i.e. release builds) then uploads `dist/clients/python/*.whl` and
  `*.tar.gz` as the `python-client-artifacts` GitHub Actions artifact (ubuntu leg only). Build
  backend: `packages/client-python/pyproject.toml` `[build-system] requires =
  ["setuptools>=75","wheel"]`, `build-backend = "setuptools.build_meta"`. This step does not gate
  ordinary PRs (package upload only runs when the workflow is invoked with `package: true`, i.e.
  release/publish flows, not the default `ci.yml` → `build` call) — **not part of the per-PR
  required-check set**, but relevant to "packaging" as asked.

### nodes

- **nodes tests**: `nodes/scripts/tasks.js` `makeRunPytestAction` (task `nodes:run-pytest` /
  `nodes:run-pytest-full` for `--test_full`), same `runPytest()` helper, invoked as:
  `<ENGINE> -m pytest nodes/test -v --rootdir nodes -m "not skip_node" -n <min(cpus,8)> --dist loadgroup [--ignore-glob '**/test_*_full.py' --ignore-glob '**/test_*_full/**' unless test_full] [extra --pytest/--markers/--pytestPattern passthrough]`.
  `ENGINE = dist/server/engine` (built by `server:build`) — **needs the engine binary**. Also runs
  inside a `bracket('node-test-server', ...)` that starts the engine server first
  (`ROCKETRIDE_MOCK=nodes/test/mocks` env var — this is the shadow-mocks directory from the
  "Node test mocks shadow gotcha" memory note: it shadows real libs engine-wide for CI's dynamic
  tests). Reached the same way as client-python: `./builder test --verbose --sequential` inside
  `_build.yaml`'s "Test" step, all 3 platforms.
  Marker default excludes `skip_node`-marked tests unless the caller passes explicit `-m`/`--markers`.
  `nodes:test-contracts` (`makeRunContractTestsAction`) is a separate, narrower pytest run against
  a single file (`nodes/test/test_contracts.py`) — also engine-backed (same `ENGINE`/`runPytest`).

- **`nodes:docs-generate`**: `nodes/scripts/tasks.js` `makeDocsGenerateAction` — runs
  `node nodes/scripts/gen-node-tables.mjs` (cwd `nodes/`). **Pure Node, no engine needed.** Part of
  the `nodes:build` step chain (`['server:build', 'nodes:sync', 'nodes:docs-generate',
  'nodes:credentials-generate']`) and separately part of `docs:build`'s `DOC_GENERATORS` list
  (`packages/docs/scripts/tasks.js:17`: `['nodes:docs-generate', 'client-typescript:docs-generate']`).
  This is the generator the co-located-docs rule in this repo's CLAUDE.md refers to for the
  `<!-- ROCKETRIDE:GENERATED:PARAMS -->` block in each node's `doc.md`/`README.md`.

- **schema checks**: **no discrete "schema check" CI job exists under that name.** The closest
  real gates are (a) `nodes:credentials-check` (`node nodes/scripts/gen-credentials.mjs --check`,
  pure Node, no engine) — run as the "credentials catalog is current" step inside ci.yml's
  `shell-contract` job; it fails if a node's `services*.json` has a credential-shaped field with no
  catalog entry, or a catalog entry has gone stale — and (b) implicit validation: the C++ engine's
  own services loader (`engLib/store/services/services.cpp`, see `research-1489.md` for the full
  trace) parses every `services*.json` at startup as part of `server:build`/`nodes:sync`/
  `./builder test`, so a structurally-malformed services file surfaces as a build/test failure
  there, not as a named pre-check. If "schema checks" was expected to be its own job, it is not —
  worth flagging back to whoever scoped this task rather than reporting a fabricated job name.

- **"Compile universal node constraints"**: workflow `lock-node-deps.yml`, job name literally
  `Compile universal node constraints` (matches the `statusCheckRollup` name seen on all 5 PRs).
  Triggers on `pull_request` only when a `nodes/src/nodes/**/requirements.txt` changed (path
  filter), or on push/schedule/dispatch to develop (which also auto-commits/opens a PR with the
  regenerated lockfile). On a PR it's **compile-only** (`uv pip compile --universal --no-header
  --emit-index-url --no-build-isolation --index-strategy unsafe-best-match --output-file
  nodes/src/nodes/constraints.lock <every nodes/src/nodes/**/requirements.txt>`, pinned Python
  3.12 to match "the engine embedded Python", pinned `uv` 0.5.29) — fails the PR if the cross-node
  dependency solve conflicts; does not push. **No engine binary needed** (pure `uv`/Python
  dependency resolution), but it does execute arbitrary third-party `setup.py`/PEP 517 build
  backends from the resolved packages (`--no-build-isolation`) — which is why the job explicitly
  withholds any write-scoped token on `pull_request` events (security comment in the workflow).

### docs build (`builder docs:build`)

Workflow `docs.yml` (push to `develop` touching `packages/docs/**`, `nodes/src/nodes/**/README.md`,
`packages/*/docs/**`, `apps/*/docs/**`, or manual dispatch). Runs `node scripts/build.js docs:build`
directly (not through `./builder` in this workflow, but same effective target). Task chain
(`packages/docs/scripts/tasks.js:167-169`):
`[parallel(['nodes:docs-generate','client-typescript:docs-generate']), 'docs:gather', 'docs:index', 'docs:compile']`
— gather co-located docs into `build/docs-content`, build the node catalog landing page + LLM
surface, then Docusaurus-compile to `dist/docs`. **Pure Node/pnpm, no engine binary needed** at any
step (confirmed: no `server:build`/`ENGINE` reference anywhere in `packages/docs/scripts/tasks.js`
or `docs.yml`). Deploys to GitHub Pages on `develop` only — **not a per-PR required check today**
(no `pull_request` trigger in `docs.yml` at all), so `builder docs:build` matters here only as the
CLAUDE.md-mandated local verification step for doc-affecting changes, not as a CI gate that blocks
these 5 PRs. `fetch-depth: 0` is required (full clone) because `docs:gather` stamps each page with
its source file's last commit date for the sitemap.

## Required-check names GitHub reports (from the 5 PRs' `statusCheckRollup`)

Observed verbatim across the inventory JSONs (`workflowName` → `name`):
- CI → `Initialize / Build variables`, `Detect changes`, `Detect Helm changes`,
  `Build / Ubuntu 22.04`, `Build / Windows Server 2022`, `Build / macOS (ARM64)`,
  `Build / ${{ matrix.label }}` (the `build-skip` passthrough — only populated on docs-only PRs
  where the real build matrix is skipped), `Container scan / ${{ matrix.dockerfile }}` (skipped on
  PR events), `Ruff`, `gitleaks`, `Shell API contract`, `Helm lint & kubeconform` (skipped unless
  `deploy/helm/**` touched), `CI OK`, `discord-notify / notify`.
- `Lock node deps (universal constraints)` → `Compile universal node constraints`.
- `PR checks` → `Auto-label`, `discord-notify / notify`.
- `check-externals` → `check-externals (PR)`, `check-externals (nightly)` (skipped on PR events).
- `CodeRabbit` → a `StatusContext`, not a `CheckRun` (legacy commit-status API), state `SUCCESS`/etc.

Of these, only the `CI OK` aggregate is the one the codebase's own comments say should ever be
marked "Required" in branch protection; everything else is informational/advisory per the
inline warnings in `ci.yml` and `check-externals.yml` described above.

## What needs the engine binary (unavailable in this read-only review environment)

Everything that ultimately calls `runPytest()` with `engine = dist/server/engine` needs a full
native build first (`./builder build`, which itself needs vcpkg + a C++ toolchain — 90-minute CI
timeout on 3 platforms):
- `client-python:run-pytest` (all client-python tests)
- `nodes:run-pytest` / `nodes:run-pytest-full` (all node tests)
- `nodes:test-contracts` (`nodes/test/test_contracts.py`)
- transitively, `./builder test` (CI's actual "Test" step) and this repo's own CLAUDE.md
  `python -m pytest <path>` "Common Commands" entry is at best a partial local substitute — it
  will run *pure-Python* test files that don't require a live engine connection, but any test
  hitting the `ROCKETRIDE_URI`/live-server fixtures will fail or be skipped without one.
- `check-externals:run` (both PR and nightly lanes) — explicitly builds the engine + "the four
  trees" before invoking its CLI.

Not engine-dependent (safe to run standalone in this environment): `ruff check` / `ruff format
--check`, `gitleaks detect`, `nodes:docs-generate`, `nodes:credentials-check`,
`client-typescript:docs-generate`, `docs:gather`/`docs:index`/`docs:compile` (`builder docs:build`),
`lock-node-deps.yml`'s `uv pip compile`, `npx tsc --noEmit` (shell-contract's `shell:check`/
`shell:regen-derived`, pnpm/Node only).
