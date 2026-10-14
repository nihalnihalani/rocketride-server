# Vector Explorer

Vector Explorer (`apps/vector-ui`, app id `rocketride.vector`) is the shell app
for managing and visualising the documents in a vector store through a store
node in a running pipeline: counts, a directory of documents with removal, drag
and drop ingest, a chat over the documents, and a map of how close the chunks
are. This page is for people changing the app, the store tools it calls, or the
drivers behind them.

- What users see is the public guide,
  <https://docs.rocketride.org/guides/apps/vector-explorer> (source:
  `docs/public/product/guides/apps/vector-explorer.md`).
- Every hook, tool, JSON shape, code, caveat and limit between the app and the
  nodes is the [Vector store tool contract](../nodes/vector-tool-contract.md).
  This page does not repeat it; it says where things live and how they fit.
- The discovery, session and role-channel code it shares with SQL Explorer and
  Graph Explorer is the [Explorer library](explorer-library.md).

## Where the pieces live

| Piece | Location |
| --- | --- |
| The app | `apps/vector-ui/` |
| The app's view of every answer, and the selection bridge between the console and the map | `apps/vector-ui/src/contract/` (`types.ts`, `bridge.ts`) |
| Discovery, roles, role channels, tool sessions | `apps/shared/src/explorer/` |
| Optional driver hooks and their defaults | `packages/ai/src/ai/common/store/document_store.py` (`DocumentStoreBase`) |
| The store tools | `packages/ai/src/ai/common/store/vx_tools.py`, mixed into `VectorStoreToolMixin` |
| Write gate | `packages/ai/src/ai/common/store/vx_write_gate.py` |
| Similarity, PCA, kNN, density, duplicates, sampling helpers | `packages/ai/src/ai/common/store/vx_math.py` |
| Per-instance sample cache | `packages/ai/src/ai/common/store/vx_sample_cache.py` |
| Value types, vocabularies, exceptions | `vx_types.py`, `errors.py` beside them |
| Write-switch defaults and tool limits (one source) | `packages/ai/src/ai/common/store/vx_defaults.py` |
| The shared pgvector driver (`store_postgres` and `rocketride_vector`) | `packages/ai/src/ai/common/store/pgvector/` |
| Call context of a tool invoke | `packages/ai/src/ai/common/tool_context.py` |
| Tool audience (`agent`, `dap`) | `@tool_function(audience=...)` in `packages/server/engine-lib/rocketlib-python/lib/rocketlib/filters.py` |
| The `embed` tool on the embedding nodes | `packages/ai/src/ai/common/embed_tool.py`, used by `embedding_transformer` and `embedding_openai` |
| Store nodes | `nodes/src/nodes/{store_postgres,rocketride_vector,store_qdrant,store_chroma,store_milvus,store_weaviate,store_pinecone,store_astra,store_atlas}/` |
| The write switches as node fields | `vector.allow_writes` and `vector.agent_writes` in `nodes/src/nodes/core/services.common.vector.json`; `rrvector.*` on `rocketride_vector` |
| Starting pipelines | `apps/vector-ui/templates/*.pipe` |
| Wire fixtures and generators | `apps/vector-ui/tests/fixtures/` |
| Live acceptance (engine, containers, stub LLM, browser lanes) | `scripts/acceptance/vector-explorer/` ([README](../../../scripts/acceptance/vector-explorer/README.md)) |

## How a call travels

1. **Discovery.** The app's endpoint store is the shared library's, created
   with `VECTOR_ROLES`. It reads the running tasks and groups the three sources
   of one project (`ingest_1`, `chat_1`, `tools_1`, matched by source id or by
   the provider of the source: Drag & Drop or Webhook, Chat, Tools) into one
   connection per store node. The anchor is the Tools source when it runs;
   otherwise the Chat source, then the Ingest source, and the connection is
   read-only. With a Tools source, only the store nodes it controls are listed
   (`nodeFilter`), so the chat-side `store_2` never appears. The provider list
   is pinned from each store's `services.json`, so SQL and Graph stores are
   never listed, and Elasticsearch/OpenSearch are left out on purpose.
2. **Probe.** One `dialect` call per store node, on the anchor role's token. It
   answers the provider, backend, collection, metric, model, dimension, score
   definition, support level, write switches, capabilities, limits, health and
   caveats, and never a host, DSN, credential or database name.
3. **Tool calls.** `store.channel(client, endpoint, role)` returns a channel
   bound to one role's token; `invoke(tool, input, { nodeId })` sends a DAP
   `tool` request that always names the node. The engine checks the data
   permission on the calling task and dispatches inside that task's process to
   the named node. Tool calls, uploads and questions are never retried.
4. **On the node.** `VectorStoreToolMixin` wraps every tool: input
   normalisation, the `{success, ...}` envelope, numpy values to lists,
   rounding and the size check. The tool calls the driver's hooks; a hook the
   driver does not override answers with the base default or `UNSUPPORTED`.
5. **Ingest is not a tool call.** The app sends files with
   `channel('ingest').sendFiles(...)` to the Ingest source; the parser,
   chunker, embedder and `store_1` write them through the data lane. Each file
   carries `objinfo: { name: <path>, origin: 'vector-explorer' }` and never an
   `objectId`.
6. **Chat.** `channel('chat').ask(...)` runs the chat path; the answer carries
   `answers` and, through `response_2`, the retrieved `documents` the sources
   panel and the map use.
7. **Map.** `sample` returns positions computed on the node (PCA), a kNN graph
   (native on Qdrant), density, outliers and duplicates; `project`,
   `neighbors` and `search` take a query vector from `embed`. Raw vectors leave
   the node only through `vectors` (two keys at most). The browser refines the
   layout in a worker (a seeded force layout over the kNN graph, or exact t-SNE
   up to 1,000 points), and keeps the force layout only when it preserves
   neighbours at least as well as PCA (`map/quality.ts`).

### Why the pipeline has two store nodes

The templates (and the contract's §5 "VX shape") give the managed store,
`store_1`, the documents lane and the Tools source's control, and put a second
instance of the same provider and collection, `store_2`, on the chat's
questions lane. The engine rejects one store node that is both fed by the data
lane and drives the chat's sub-pipeline, so the two roles are split. `store_2`
keeps `allow_writes` false and the app never lists it. When a pipeline has only
one store node, the app falls back to reaching `embed` through the chat role
and disables text queries on the map, with the reason, when nothing reaches it.

## The app

`apps/vector-ui/src/`:

| Folder | What is in it |
| --- | --- |
| `adapters/` | The one seam to the shared library and the shell: provider list, tool names, the endpoint store with its roles and node filter, history, the announcer, the per-connection request channel for `neighbors` |
| `contract/` | The wire types and the selection bridge, changed only together with the contract (see [Changing the contract](#changing-the-contract)) |
| `vector/` | Pure modules tested under `node:test`: addresses, connections, stats, the document tree and its background pager, pure-JS SHA-1 and the uuid5 objectId, file types, upload batching, chat results, retrieval, safe markdown, wording, colours, support levels, identity changes, budgets, panel ratios |
| `map/` | Renderer (WebGL points with a Canvas2D fallback), camera, picking, lasso, the layouts and their worker, the layout-quality metric, query projection |
| `chat/`, `ingest/` | The chat and upload hooks and the folder-drop traversal |
| `views/`, `components/` | Connections, the console (the default view), the map and the document tab, and their parts |

Rules the tests pin:

- **Tokens stay in memory.** No task token in a snapshot, history entry,
  preference or log. Signing out or switching organization or team clears every
  per-connection cache.
- **No raw vectors in the map.** No module under `src/map/` receives a raw
  vector; it works on the node's positions and kNN graph.
- **No `crypto.subtle`.** The collision check derives the engine's objectId
  (uuid5 of `null://Stream/<path>`) with the pure-JS SHA-1 in
  `vector/sha1.ts`, because `crypto.subtle` is missing on plain-HTTP origins
  other than localhost.
- **Safe answers.** Model output goes through `vector/markdown.ts`: no raw
  HTML, no remote images, links with `rel="noopener noreferrer nofollow"`.
- **Every code and caveat has a sentence** in `vector/wording.ts`.
- **Configuration stays private.** From a pipeline's configuration the app
  reads only the provider, node name, pipeline name and collection.
- **Same-name uploads.** The upload queue sends files whose base name repeats
  within one drop one at a time, because upload progress events are keyed by
  file name.

Builder tasks (see the [builder reference](../builder/reference.md)):

```bash
./builder vector-ui:build     # bundle into dist/server/static/apps, register in apps.json
./builder vector-ui:dev       # rsbuild dev server on port 3103
./builder vector-ui:test      # node:test over apps/vector-ui/tests
./builder vector-ui:e2e-live  # browser lanes against ENGINE_URL; opt-in, not part of test or CI
```

## The write switch

- **One source for the defaults.** `VECTOR_ALLOW_WRITES_DEFAULT` (false) and
  `VECTOR_AGENT_WRITES_DEFAULT` (true) live in `vx_defaults.py`.
  `apps/vector-ui/scripts/gen_defaults.py` exports them, with the tool limits,
  to `apps/vector-ui/tests/fixtures/defaults.json`, and `--check` fails when
  the JSON is stale. The node, the app's templates test and the tool-path
  suite's expectation table all read that value, so changing a default is one
  line plus regenerating the JSON.
- **Where it lives in a pipe.** `config[config.profile].allow_writes` on the
  store component (contract §6.1). The templates set it explicitly: `true` on
  `store_1`, `false` on `store_2`.
- **The gate** (contract §6.3) runs first in `remove_document`, `delete` and
  `upsert`, fails closed, and answers refusals as envelopes; the write tools
  stay listed. Agent pipelines keep writing with the defaults (`agent_writes`).
- **Ingest is not gated by the switch.** Files dropped on the Ingest source
  are written through the data lane; only the reserved objectId `schema` (the
  collection's control record) is refused there.

## Changing the contract

A change to a hook, tool, JSON shape, code, caveat or limit is one change
across:

1. the [contract page](../nodes/vector-tool-contract.md);
2. `vx_types.py` or `vx_defaults.py`, then
   `python3 apps/vector-ui/scripts/gen_defaults.py` to refresh `defaults.json`;
3. `apps/vector-ui/src/contract/types.ts` (a component that needs more props
   extends the contract interface in its own file instead);
4. the provisional fixtures, and the live captures when the wire output
   changes (see [Fixtures](#fixtures));
5. `vector/wording.ts` for a new code or caveat;
6. the public guide when users see the difference.

New tools are `@tool_function(..., audience=('dap',))` under the
`vectordb_tool` wrapper. The agent catalog does not change: the six legacy
store tools (`search`, `stats`, `delete`, `get`, `objdir`, `upsert`) keep their
descriptors byte-for-byte, and `test_tool_audience.py` pins that.

## Adding or changing a store driver

- Override the hooks your backend can answer natively and inherit the rest.
  List anything else the backend does natively (for example
  `sample_stratified_native` or `knn_native`) in `VX_DRIVER_CAPABILITIES`;
  `capabilities()` and `dialect` report it.
- Every hook works on **legacy collections**, written by older drivers: random
  point ids, documents whose chunk 0 is missing, no `size`/`modifyTime`/
  `ingestedAt`, and no `meta` column on pgvector.
- `describe()` and `dialect` never carry a host, port, DSN, credential or
  database name.
- The control-record path stays open: `createCollection` writes `schema`
  through `addChunks(..., checkCollection=False)`, so no driver refuses it
  there; the external write paths refuse it.
- **pgvector:** every read and write is one self-contained transaction, with
  no session-level `SET`, because the managed store reaches tenant databases
  through a transaction-mode pooler.
- **Mocks.** `nodes/test/mocks/` replaces the store clients for the whole
  engine under `ROCKETRIDE_MOCK`. A driver that starts using a new native call
  adds it to that client's mock and pairs the mocked assertion with the same
  assertion in the unmocked suite. Do not mock numpy there.
- **Support level.** `dialect.support` is `supported` only for a provider whose
  unmocked live suite passes on a new and a legacy collection (and, for the two
  pgvector providers, through the pooler). Everything else is `experimental`,
  and a mocked test never changes that.

## Tests

| Suite | Files | Run with |
| --- | --- | --- |
| Tool mixin, hooks, math goldens, write gate, envelope and caps | `nodes/test/test_vectordb_tool_mixin.py`, `test_vector_hooks.py`, `test_vector_math.py`, `test_vector_write_gate.py`, `test_vector_tool_envelope.py` | `./builder nodes:test` (mocked pass) |
| The `embed` tool | `nodes/test/test_embed_tool.py` | `./builder nodes:test` |
| Call context and tool audience | `test_tool_context.py`, `test_tool_audience.py` | `./builder ai:test` |
| Live `rocketride_vector` driver on new and legacy collections | `nodes/test/test_rocketride_db_full.py` | `./builder nodes:test-db`, or by name |
| Live `store_postgres`, Qdrant and Chroma drivers on new and legacy collections | `nodes/test/test_store_postgres_full.py`, `test_store_qdrant_full.py`, `test_store_chroma_full.py` | By name |
| Every tool through a real engine and the shipped templates | `nodes/test/test_vector_toolpath_full.py` (needs `dist/server`) | By name |
| Wire fixtures still match the drivers | `nodes/test/test_vector_wire_fixtures_full.py` | By name |
| The app | `apps/vector-ui/tests/*.test.ts` | `./builder vector-ui:test` |
| Browser lanes | `scripts/acceptance/vector-explorer/` | `./builder vector-ui:e2e-live`, manual |

`./builder nodes:test-db` runs only the suites listed in `DB_LIVE_SUITES` in
`nodes/scripts/tasks.js`, and of the vector live suites that list holds only
`test_rocketride_db_full.py`. Run the others by name with the engine in
`dist/server`:

```bash
cd dist/server
export RR_REQUIRE_DB_TESTS=1   # an unreachable server fails the suite instead of skipping it
./engine -m pytest ../../nodes/test/test_store_postgres_full.py ../../nodes/test/test_store_qdrant_full.py ../../nodes/test/test_store_chroma_full.py -q -rs
./engine -m pytest ../../nodes/test/test_vector_toolpath_full.py -q -rs
./engine -m pytest ../../nodes/test/test_vector_wire_fixtures_full.py -q -rs
```

Without `RR_REQUIRE_DB_TESTS` a suite whose server is unreachable skips with a
`NOT RUN:` reason, so a run can pass without touching a database; read the skip
summary that `-rs` prints. A run by name also leaves out the checks
`nodes:test-db` adds to a required run (every suite passes at least one test,
and no test skips without a `NOT RUN:` reason); see
[Live database tests](../nodes/testing.md#live-database-tests).

The pooler pass is part of the suites themselves: the driver cases in
`test_store_postgres_full.py` and the `rocketride_vector` cases in
`test_rocketride_db_full.py` run once against the database and, with
`RR_TEST_PGVECTOR_POOLER_DSN` set, once more through that transaction-mode
pooler, and `test_vector_toolpath_full.py` runs `rocketride_vector.pipe` through
it a second time. Without the variable those cases skip with `NOT RUN:`. The
servers, their pinned images and the local ports are in the acceptance
[README](../../../scripts/acceptance/vector-explorer/README.md).

## Fixtures

| Folder | What | How it is made |
| --- | --- | --- |
| `apps/vector-ui/tests/fixtures/provisional/` | One hand-written answer per tool and case, including the error envelopes | By hand, from the contract |
| `apps/vector-ui/tests/fixtures/v1/live/<backend>/` | Answers captured from the live drivers, on a new and a legacy collection, scrubbed of volatile values | `nodes/test/vector_wire_fixtures.py`; `test_vector_wire_fixtures_full.py` regenerates and compares |
| `sample_*.json` among the provisional fixtures | Seeded synthetic `sample` answers for the map's tests | `apps/vector-ui/tests/fixtures/gen_sample.ts` (`--check` verifies them) |
| `defaults.json` | The write defaults and tool limits | `apps/vector-ui/scripts/gen_defaults.py` (`--check`) |
| `chunking.json` | The chunker settings every template carries | The chunking calibration run |

Regenerate the live captures only against the pinned container images: they
record each server's version.

## Running it locally

1. Build: `./builder build` (engine, nodes and the shell apps into
   `dist/server`), then `./builder vector-ui:build` after an app change.
2. Start the containers, the fake broker, the stub LLM and an engine on a
   fresh store exactly as the acceptance
   [README](../../../scripts/acceptance/vector-explorer/README.md) says. An
   engine seeds an app version once per store, so use a fresh store after a
   rebuild (see "Trying a production build on a local engine" in
   [the apps index](index.md#trying-a-production-build-on-a-local-engine)).
3. Start the fixture pipelines with `start_fixtures.py` (one per supported
   store, all three sources, no idle timeout, the stub LLM in place of a
   model).
4. Open the engine's URL in a browser, sign in with any non-empty key on an
   OSS engine, and open Vector Explorer.

The stub LLM is a test stand-in: answers start with `[STUB-LLM]` and prove that
retrieval reached the LLM node, nothing about answer quality.
