# Graph Explorer acceptance lanes (manual)

Live checks for Graph Explorer and SQL Explorer that the unit suites cannot
make: a real engine loads the graph nodes, the SDKs call their tools against
real databases, and Playwright drives the production shell in real browsers.

**These lanes are manual. They are not wired into CI**, and nothing in
`./builder test` runs them. CI covers the pure-logic tests, the node suites
(which stub the engine's tool registration) and the template structure; it
does not start a graph node in an engine or render the apps in a browser. Run
these lanes before a release, or when a change touches tool registration or
dispatch, the shipped templates, the task lifecycle, or the explorer UI. The
browser lanes can also be run on request as one builder action,
`./builder graph-ui:e2e-live` (see "Through the builder" below); it is opt-in
too, and no CI workflow runs it.

Everything here is for **disposable local containers only**. The scripts create
and drop their own graphs and tables (named below), and every credential they
default to is a throwaway local-only test value for those containers, not a
secret. Never point them at a database that holds data you care about.

## What is here

| File | What it checks |
| --- | --- |
| `graph_acceptance.py` | Python SDK -> engine -> graph node -> database, per engine (AGE, Neo4j, FalkorDB): task discovery with `get_tasks()`, `dialect`, `get_schema` / `refresh_schema`, `read_query` (positional rows, paths and direction, ids past 2^53, row-limit truncation, invalid input), and that writes and `execute` are refused, proved by database state read over an independent connection. `--pipe-dir apps/graph-ui/templates` runs the shipped templates. |
| `graph_acceptance.cjs` | The same path through the TypeScript SDK: what a browser-side client receives (number tags for unsafe integers, escaped `@` keys, typed `DAPException` refusals). |
| `graph_lifecycle.py` | What a tool caller sees for an unwired node, a stopped task, and a task during a restart (only `TASK_STOPPED`, then success on the same token). The restart rows fail when no call landed in the restart window, so rerun it then. |
| `start_fixtures.py` | Starts the long-lived tools pipelines the browser lanes use, with no idle timeout (the engine otherwise stops a task after 15 idle minutes); `--stop` terminates them. |
| `fake_broker.py` | Local stand-in for the DB broker's `/provision` endpoint, so `rocketride_graph` and `rocketride_sql` resolve a local database. |
| `validate_all.sh` | Runs every repository gate the feature touches (unit, SDK, node, docs, builds), writes one log per step, and exits non-zero when any step failed. |
| `browser/lane_graph.cjs` | Graph Explorer in Chrome, Firefox and WebKit: connections, drawer, editor run, canvas, Table/Raw tabs, inspector open and Escape, Expand, schema Refresh, History, write refusal, Ask without an LLM. |
| `browser/lane_sql.cjs` | SQL Explorer in the three browsers: connections listed (no graph nodes), each card's Edit reachable as a button (not inside the card's own button), a query through the shared runner. |
| `browser/lane_a11y.cjs` | Themes, reduced motion, WCAG text contrast on the landing, canvas, Table view and inspector, and relationship-stroke contrast on the drawn graph. |
| `browser/probe_linenumbers.cjs` | Editor line-number colour and contrast in both themes, both apps. |
| `browser/lane_perf.cjs`, `browser/gen_perf.py` | Canvas performance on a seeded FalkorDB graph (first draw, pan and drag frame times, long tasks, Expand round trips), Chrome with CPU throttling. |
| `demo/seed_demo.sh`, `demo/start_demo.py`, `demo/take_shots.cjs` | A small fictional dataset, demo pipelines and the product screenshots. |
| `local_env.py`, `env.cjs` | Settings shared by the Python and Node scripts, read from the environment. |
| `selftest/` | Checks of the harness's own verdicts, with no engine, database or browser (see "Self-tests"). |

## Prerequisites

### 1. Builds

From the repository root:

```bash
./builder build                    # engine, nodes and the shell apps, into dist/server
./builder client-typescript:build  # for graph_acceptance.cjs (dist/cjs)
git checkout -- packages/client-typescript/src/client/constants.ts  # the build rewrites it
```

The browser lanes test whatever `dist/server/static` serves, so rebuild the
apps (`./builder graph-ui:build sql-ui:build`) after a UI change. An engine
seeds an app version once per store, so start it on a fresh store after a
rebuild (see "Trying a production build on a local engine" in
`docs/development/apps/index.md`). The lanes open a fresh browser context for
every run, so no cached bundle masks the served build.

### 2. Database containers

Local-only throwaway values, published on 127.0.0.1 only:

```bash
docker run -d --name gx-age -p 127.0.0.1:55433:5432 \
  -e POSTGRES_USER=rruser -e POSTGRES_PASSWORD=rrpass -e POSTGRES_DB=rrtenant \
  apache/age:release_PG16_1.5.0 -c shared_preload_libraries=age
docker run -d --name gx-pgvector -p 127.0.0.1:55432:5432 \
  -e POSTGRES_USER=rruser -e POSTGRES_PASSWORD=rrpass -e POSTGRES_DB=rrtenant \
  pgvector/pgvector:0.8.0-pg16
docker run -d --name gx-neo4j -p 127.0.0.1:57687:7687 -p 127.0.0.1:57474:7474 \
  -e NEO4J_AUTH=neo4j/gxlocal-test-pass -e NEO4J_server_memory_heap_max__size=512m \
  neo4j:5.26-community
docker run -d --name gx-falkordb -p 127.0.0.1:56379:6379 falkordb/falkordb:latest

# The AGE image creates the extension in rrtenant on first start; this is a no-op then.
docker exec gx-age psql -U rruser -d rrtenant -c 'CREATE EXTENSION IF NOT EXISTS age'
```

In a cloud tenant the provisioner creates the AGE graph `rocketride` and the
tenant reaches its database through a PgBouncer pooler in transaction mode.
Locally the scripts create their own graphs. To exercise the pooled path, run
a PgBouncer in transaction mode in front of `gx-age` (for example
`edoburu/pgbouncer` with `POOL_MODE=transaction`) and give the fake broker its
DSN instead of the direct one.

The Python scripts need `rocketride`, `psycopg2`, `neo4j` and `falkordb`; the
engine in `dist/server` has them, so run them with `./engine <script>` from
`dist/server` (shown below). A virtualenv with those packages works too.

### 3. Fake broker and engine

`rocketride_graph` and `rocketride_sql` get their database from the DB broker.
Point the engine at the local stand-in; the token is any placeholder you pick
(it only has to match on both sides):

```bash
python3 scripts/acceptance/graph-explorer/fake_broker.py 18787 local-broker-placeholder \
  'postgresql://rruser:rrpass@127.0.0.1:55433/rrtenant?sslmode=disable' &

STORE_DIR=$(mktemp -d)   # a fresh, disposable store; never your ~/.rocketlib/store
(cd dist/server && \
  RR_STORE_URL=filesystem://$STORE_DIR \
  RR_DB_BROKER_URL=http://127.0.0.1:18787/provision \
  RR_DB_BROKER_TOKEN=local-broker-placeholder \
  ./engine ai/eaas.py --host=127.0.0.1 --port=5580) &
```

Leave `ROCKETRIDE_APIKEY` unset: an OSS engine then accepts any non-empty key,
and the scripts sign in with `RR_TEST_APIKEY` (a local label, default
`local-acceptance-key`).

### 4. Playwright (browser lanes only)

```bash
cd scripts/acceptance/graph-explorer/browser
npm install --no-package-lock            # Playwright, local to this folder; not a workspace package
npx playwright install firefox webkit    # Chrome lanes use the installed Google Chrome
```

Set `PLAYWRIGHT_DIR` instead to use a Playwright installed elsewhere, and
`PLAYWRIGHT_BROWSERS_PATH` if the browsers live outside Playwright's default
cache.

## Settings

All optional; the defaults match the containers above.

| Variable | Default | Used for |
| --- | --- | --- |
| `ENGINE_URL` | `http://127.0.0.1:5580` | the engine under test |
| `RR_TEST_APIKEY` | `local-acceptance-key` | sign-in on an OSS engine without `ROCKETRIDE_APIKEY` |
| `OUT_DIR` | `out/` in this folder (git-ignored) | JSON results, screenshots, logs |
| `CLIENT_TS_DIR` | `packages/client-typescript` | the built TypeScript SDK for `graph_acceptance.cjs` |
| `STORE_DIR` | a new temp dir | `validate_all.sh`: the store for the test servers the builder starts |
| `AGE_DSN` | the `gx-age` DSN | seeding and measuring the AGE graphs |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | `gx-neo4j` | Neo4j node config and seeding |
| `FALKORDB_HOST`, `FALKORDB_PORT` | `127.0.0.1`, `56379` | FalkorDB node config and seeding |
| `SQL_HOST`, `SQL_USER`, `SQL_PASSWORD`, `SQL_DATABASE` | `gx-pgvector` | SQL fixtures |
| `SQL_TABLE` | `gx_items` | SQL fixture table; `start_fixtures.py` creates it with 25 rows when missing and never changes an existing one |
| `ACCEPT_GRAPH` | `gx_accept` | graph the acceptance seeds (dropped and recreated on AGE and FalkorDB) and the fixtures read |
| `RUN_LABEL` | `GxAcc` | label on every Neo4j node the acceptance seeds or writes as a probe; on Neo4j the acceptance deletes and counts only nodes with this label |
| `PERF_GRAPH` | `gx_perf` | FalkorDB graph `gen_perf.py` drops and recreates |
| `DEMO_GRAPH`, `DEMO_SQL_PREFIX` | `gx_demo`, `demo_` | demo graph and tables `seed_demo.sh` drops and recreates; on Neo4j it deletes every node with `demo: true`, whoever created it |

Pick your own `ACCEPT_GRAPH` and `RUN_LABEL` when someone else may run the
lanes against the same containers at the same time.

## Running the lanes

From the repository root, with the engine and fake broker running:

```bash
REPO=$PWD
ACC=$REPO/scripts/acceptance/graph-explorer
export ENGINE_URL=http://127.0.0.1:5580 OUT_DIR=$ACC/out
mkdir -p "$OUT_DIR"

# SDK and tool path (seeds ACCEPT_GRAPH first; run it before everything else)
(cd dist/server && ./engine $ACC/graph_acceptance.py --engine all --json $OUT_DIR/acceptance.json)
(cd dist/server && ./engine $ACC/graph_acceptance.py --engine all --pipe-dir $REPO/apps/graph-ui/templates)
node $ACC/graph_acceptance.cjs all
(cd dist/server && ./engine $ACC/graph_lifecycle.py)

# Browser lanes: seed the perf graph (its fixture does not start without it),
# start the fixtures, then run any lane ([chrome|firefox|webkit|all])
(cd dist/server && ./engine $ACC/browser/gen_perf.py 300)
(cd dist/server && ./engine $ACC/start_fixtures.py)
node $ACC/browser/lane_graph.cjs "$ENGINE_URL" "$OUT_DIR" all
node $ACC/browser/lane_sql.cjs "$ENGINE_URL" "$OUT_DIR" all
node $ACC/browser/lane_a11y.cjs "$ENGINE_URL" "$OUT_DIR" all
node $ACC/browser/probe_linenumbers.cjs "$ENGINE_URL" "$OUT_DIR" all

# Canvas performance (Chrome) on the seeded graph, at CPU throttling 1x and 4x
node $ACC/browser/lane_perf.cjs "$ENGINE_URL" "$OUT_DIR/perf-300.json" 300 1,4

# Repository gates (no engine needed; containers needed for the node suites)
$ACC/validate_all.sh
```

Every lane prints one `PASS` / `FAIL` line per check and exits non-zero when
any check failed; a check whose prerequisite is missing, or that could not
observe what it checks, fails rather than being skipped. `validate_all.sh`
prints one `exit=` line per step and exits non-zero when any step failed. The
browser lanes also write a screenshot per step and a JSON result file to the
output folder. `lane_perf.cjs` reports measurements, not pass/fail.

The browser lanes find elements by their visible names (button labels,
fixture names), so a UI wording change can break a lane without a product
defect: read the step's screenshot before filing one.

`lane_a11y.cjs` measures every visible text element, including the shell's own
navigation and the shell theme tokens Graph Explorer reuses
(`--rr-text-secondary`, `--rr-brand`). Some of those shell theme pairs are
below 4.5:1 today, so its contrast rows can fail on text Graph Explorer does
not colour. `lane_a11y.json` groups each failure by the theme token that drew
it (`byToken`) and by region, so check those before treating a contrast row as
a Graph Explorer defect.

### Through the builder

`./builder graph-ui:e2e-live` runs the pass/fail browser lanes (`lane_graph`,
`lane_sql`, `lane_a11y`, `probe_linenumbers`; not `lane_perf`) against a
running engine and ends with one summary. It is opt-in: nothing in
`./builder test`, `graph-ui:test` or CI runs it. It does not set anything up:
start the engine, the fake broker and the fixtures, and seed the graphs, as
above. It checks first that `ENGINE_URL` answers, that Playwright loads and
that every chosen browser starts, and fails with a sentence naming what is
missing; then it runs each chosen lane once per browser.

```bash
ENGINE_URL=http://127.0.0.1:5580 ./builder graph-ui:e2e-live
ENGINE_URL=http://127.0.0.1:5580 GRAPH_UI_E2E_BROWSERS=all GRAPH_UI_E2E_LANES=all ./builder graph-ui:e2e-live
```

| Variable | Default | Used for |
| --- | --- | --- |
| `ENGINE_URL` | none: required | the engine under test (http or https) |
| `GRAPH_UI_E2E_BROWSERS` | `chrome` | `chrome`, `firefox`, `webkit`, `all`, or a comma list |
| `GRAPH_UI_E2E_LANES` | `graph,sql,linenumbers` | any of `graph`, `sql`, `a11y`, `linenumbers`, or `all` |
| `GRAPH_UI_E2E_ENGINES` | `age,neo4j,falkordb` | the graph lane's engines |
| `OUT_DIR` | `out/e2e` in this folder (git-ignored) | results, in one folder per browser |
| `PLAYWRIGHT_DIR`, `PLAYWRIGHT_BROWSERS_PATH` | as in "Playwright" above | where Playwright and its browsers are |

`lane_a11y` runs only when named (`GRAPH_UI_E2E_LANES=a11y`, or `all`) until
the shell's theme tokens pass 4.5:1: its contrast rows fail on the shell text
described above, so a default run that included it would always fail. When a
lane run fails, the summary lists up to ten of its failed rows from its JSON
result in `OUT_DIR/<browser>/`, or its first error line when that run wrote no
result file.

### Product screenshots

```bash
$ACC/demo/seed_demo.sh    # drops and recreates DEMO_GRAPH and the demo_* tables, deletes all Neo4j nodes with demo: true
(cd dist/server && ./engine $ACC/browser/gen_perf.py 300)
(cd dist/server && ./engine $ACC/demo/start_demo.py)
node $ACC/demo/take_shots.cjs "$OUT_DIR/shots"
```

## Self-tests

The harness's own verdict logic has small tests that need no engine, database
or browser: stand-ins replace the SDK, the Neo4j driver and Playwright. They
check that `validate_all.sh` reports a failed step in its exit status, that the
lifecycle restart rows, the Graph Explorer Ask and Escape steps, and the
`lane_a11y.cjs` contrast, stroke and reduced-motion rows cannot pass without
observing what they name, and that the Neo4j clean-up stays inside `RUN_LABEL`.
The browser self-tests run the real lane against a stand-in Playwright
(`selftest/stand_in.cjs`) that models an empty page, or a page the test
describes: the SQL Explorer card check fails when a card's Edit sits inside the
card's own button, and the Graph Explorer drawer check fails when only the
landing behind the drawer names the engine, or the drawer names another one.
Run them after changing a script here:

```bash
python3 -m unittest discover -s scripts/acceptance/graph-explorer/selftest -v
node --test scripts/acceptance/graph-explorer/selftest/*.test.cjs
```

## Cleaning up

```bash
(cd dist/server && ./engine $ACC/start_fixtures.py --stop)
# stop the engine and the fake broker, then delete $STORE_DIR and $OUT_DIR
```

The seeded graphs and tables stay in the containers until you drop them or
remove the containers.
