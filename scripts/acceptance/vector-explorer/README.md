# Vector Explorer acceptance lanes (manual)

Live checks for Vector Explorer that the unit suites cannot make: a real engine
runs the shipped templates (`apps/vector-ui/templates`) against real vector
stores, the SDKs call the store tools, and (as the lanes are added) a browser
drives the app.

**These lanes are manual. They are not wired into CI**, and nothing in
`./builder test` runs them.

Everything here is for **disposable local containers only**. The fixtures write
into their own tables and collections (named below), and every credential the
scripts default to is a throwaway local-only test value for those containers,
not a secret. Never point them at a database that holds data you care about.

## What is here

| File | What it does |
| --- | --- |
| `start_fixtures.py` | Starts one fixture pipeline per supported store from the shipped templates: pgvector (`gx-pgvector`), RocketRide Vector (through the fake broker), Qdrant (`vx-qdrant`) and Chroma (`vx-chroma`). Each has a fixed local-only project id and starts its three sources (`tools_1`, `chat_1`, `ingest_1`) with no idle timeout (`ttl=0`; the engine otherwise stops a task after 15 idle minutes). Only what is not running yet is started; `--stop` terminates them. `--llm stub` (default) points the LLM node at `stub_llm.py`; `--llm template` keeps the template's placeholder key. It also warms the tiktoken cache so the first chat does not wait for a download. |
| `stub_llm.py` | A local test stub of an OpenAI-compatible chat server, **not a model**: deterministic answers tagged `[STUB-LLM]` that quote the prompt, plain and streamed (SSE); `--tool-call NAME` answers one request with a tool call. Logs request bodies to `out/` (git-ignored). |
| `fake_broker.py` | Local stand-in for the DB broker's `/provision` endpoint, so `rocketride_vector` resolves a local database (direct, or through `vx-pgbouncer` with `--dsn`). |
| `env.cjs` | Settings shared by the Node scripts and browser lanes, read from the environment. |

## Ports

| Service | Address |
| --- | --- |
| Engine under test | `http://127.0.0.1:5590` (`ENGINE_URL`; each worktree runs its own engine on its own port) |
| Fake broker | `http://127.0.0.1:18788/provision`, token `local-broker-placeholder` |
| Stub LLM | `http://127.0.0.1:18901/v1` |
| pgvector (`gx-pgvector`) | `127.0.0.1:55432`, database `rrtenant` |
| PgBouncer, transaction mode, in front of `gx-pgvector` (`vx-pgbouncer`) | `127.0.0.1:56434` |
| Qdrant (`vx-qdrant`) | `127.0.0.1:56333` (REST), `127.0.0.1:56334` (gRPC) |
| Chroma (`vx-chroma`) | `127.0.0.1:58000` |

## Prerequisites

### 1. Builds

```bash
./builder build                    # engine, nodes and the shell apps, into dist/server
./builder client-typescript:build  # for the Node scripts (dist/cjs)
```

### 2. Containers

Published on 127.0.0.1 only, with throwaway local values. The images are pinned
so the live suites compare like with like.

```bash
docker run -d --name gx-pgvector -p 127.0.0.1:55432:5432 \
  -e POSTGRES_USER=rruser -e POSTGRES_PASSWORD=rrpass -e POSTGRES_DB=rrtenant \
  pgvector/pgvector:0.8.0-pg16
# A transaction-mode pooler in front of gx-pgvector (the pooled pass)
docker run -d --name vx-pgbouncer --link gx-pgvector:pgv -p 127.0.0.1:56434:5432 \
  -e DB_HOST=pgv -e DB_USER=rruser -e DB_PASSWORD=rrpass -e DB_NAME=rrtenant \
  -e POOL_MODE=transaction -e AUTH_TYPE=scram-sha-256 -e DEFAULT_POOL_SIZE=4 -e MAX_CLIENT_CONN=200 \
  edoburu/pgbouncer@sha256:9c78945868a6a142c7fc40ccd843bbe5a606df163c7ffce4de70e0d628d696a2
docker run -d --name vx-qdrant -p 127.0.0.1:56333:6333 -p 127.0.0.1:56334:6334 \
  qdrant/qdrant:v1.17.1@sha256:94728574965d17c6485dd361aa3c0818b325b9016dac5ea6afec7b4b2700865f
docker run -d --name vx-chroma -p 127.0.0.1:58000:8000 \
  chromadb/chroma:1.5.9@sha256:1e0b73a187a28757c572acba508c46f48c9e8b0acaf5c20e6d95cdedce1acdf6
```

### 3. Fake broker, stub LLM and engine

```bash
ACC=$PWD/scripts/acceptance/vector-explorer
python3 $ACC/fake_broker.py &        # direct DSN; add --dsn postgresql://rruser:rrpass@127.0.0.1:56434/rrtenant for the pooled pass
python3 $ACC/stub_llm.py &

STORE_DIR=$(mktemp -d)   # a fresh, disposable store; never your ~/.rocketlib/store
(cd dist/server && \
  RR_STORE_URL=filesystem://$STORE_DIR \
  RR_DB_BROKER_URL=http://127.0.0.1:18788/provision \
  RR_DB_BROKER_TOKEN=local-broker-placeholder \
  ./engine ai/eaas.py --host=127.0.0.1 --port=5590) &
```

Leave `ROCKETRIDE_APIKEY` unset: an OSS engine then accepts any non-empty key,
and the scripts sign in with `RR_TEST_APIKEY` (a local label, default
`local-acceptance-key`).

### 4. Fixtures

```bash
(cd dist/server && ./engine $ACC/start_fixtures.py)                  # all four, stub LLM
(cd dist/server && ./engine $ACC/start_fixtures.py --only qdrant)    # one
(cd dist/server && ./engine $ACC/start_fixtures.py --stop)           # terminate them
```

The first start installs and loads the embedding model (`all-MiniLM-L6-v2`),
which can take a minute or more; later starts take seconds. The stores create
their collection on the first ingest; the script itself never creates, drops or
rewrites a table or collection.

## Settings

All optional; the defaults match the containers above.

| Variable | Default | Used for |
| --- | --- | --- |
| `ENGINE_URL` | `http://127.0.0.1:5590` | the engine under test |
| `RR_TEST_APIKEY` | `local-acceptance-key` | sign-in on an OSS engine without `ROCKETRIDE_APIKEY` |
| `OUT_DIR` | `out/` in this folder (git-ignored) | results, screenshots, logs |
| `VX_TEMPLATES_DIR` | `apps/vector-ui/templates` | the templates the fixtures start from |
| `VX_STUB_LLM_URL` | `http://127.0.0.1:18901/v1` | the stub LLM the fixtures point at |
| `VX_COLLECTION` | `vx_demo_docs` | table / collection of the pgvector, Qdrant and Chroma fixtures |
| `VX_RR_TABLE` | `vx_demo_rr` | table of the RocketRide Vector fixture |
| `VX_PG_HOST`, `VX_PG_PORT`, `VX_PG_USER`, `VX_PG_PASSWORD`, `VX_PG_DATABASE` | `gx-pgvector` | the pgvector fixture's connection |
| `VX_QDRANT_HOST`, `VX_QDRANT_PORT` | `127.0.0.1`, `56333` | the Qdrant fixture's connection |
| `VX_CHROMA_HOST`, `VX_CHROMA_PORT` | `127.0.0.1`, `58000` | the Chroma fixture's connection |

## Notes

- The fixture pipelines carry the templates' write switch: removing documents
  is on for `store_1` and off for `store_2`.
- The stub LLM is a test stand-in. Answers tagged `[STUB-LLM]` prove that
  retrieval reached the LLM node, nothing about answer quality.
- The stub's request log and the engine's run logs hold document text; keep
  `out/` and the store directory local and delete them when done.
