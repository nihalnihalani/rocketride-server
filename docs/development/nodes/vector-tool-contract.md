# Vector store tool contract

The interface between the vector store nodes and Vector Explorer
(`apps/vector-ui`): the optional driver hooks on `DocumentStoreBase`, the tools
on `VectorStoreToolMixin` and their JSON, the pipeline shape the app expects,
and the write gate. Read it before changing a store driver, the store tools, the
`embed` tool on the embedding nodes, or the app's tool calls.

Where it lives in code:

| What | File |
| --- | --- |
| Hook signatures and base defaults | `packages/ai/src/ai/common/store/document_store.py` (`DocumentStoreBase`) |
| Hook value types and vocabularies (codes, capabilities, caveats) | `packages/ai/src/ai/common/store/vx_types.py` |
| Hook and tool exceptions | `packages/ai/src/ai/common/store/errors.py` |
| Write-switch defaults and tool limits (the single source) | `packages/ai/src/ai/common/store/vx_defaults.py`, exported to `apps/vector-ui/tests/fixtures/defaults.json` by `apps/vector-ui/scripts/gen_defaults.py` |
| Call context of a tool invoke | `packages/ai/src/ai/common/tool_context.py` |
| Tool audience | `@tool_function(audience=...)` in `packages/server/engine-lib/rocketlib-python/lib/rocketlib/filters.py` |
| The app's view of every answer | `apps/vector-ui/src/contract/types.ts` |
| Example answers | `apps/vector-ui/tests/fixtures/provisional/` (hand-written), `apps/vector-ui/tests/fixtures/v1/live/` (captured) |

A change to any signature, JSON shape, code or limit here is a contract change:
update this page, the files above and the app's contract types in the same change.

How the app, the shared Explorer library and these nodes fit together, and
which suites test them, is in [Vector Explorer](../apps/vector-explorer.md).
What users see is in the public guide,
<https://docs.rocketride.org/guides/apps/vector-explorer>.

Path legend: `ds` = `packages/ai/src/ai/common/store/document_store.py`; `sgb` = `.../store_global_base.py`; `sib` = `.../store_instance_base.py`; `dm` = `packages/client-python/src/rocketride/schema/doc_metadata.py`; `df` = `.../doc_filter.py`; `q` = `.../question.py`; `dc` = `packages/ai/src/ai/modules/data/data_conn.py`; `cmd_data` = `packages/ai/src/ai/modules/task/commands/cmd_data.py`; `host` = `packages/ai/src/ai/common/agent/_internal/host.py`; `flt` = `packages/server/engine-lib/rocketlib-python/lib/rocketlib/filters.py`; `types` = `.../rocketlib/types.py`. Line references (`file:line`) point at the code as it stood before this contract was implemented and drift as the code changes.

---

## 1. Principles

1. **The app never talks to a database.** Every call is a tool call on a node of the user's pipeline through the engine, which checks `task.data` on the calling task (`cmd_data.py:136`) and dispatches by node id inside the task subprocess (`dc:1001-1037`). Tool names are bare method names (`flt:1116-1127`); the app always passes `nodeId`.
2. **Optional, non-abstract hooks** on `DocumentStoreBase`. A driver that does not override a hook gets the base default or `StoreUnsupported`, which the mixin maps to `{success:false, code:'UNSUPPORTED'}`. No driver is rewritten to ship.
3. **Logical key** is `(objectId, chunkId)`. Every hook and tool excludes `objectId == 'schema'` (the control record, `ds:505-535`) from listings and refuses it on every external write path (§6.3). Chunk 0 is the preferred display row; a document without chunk 0 is still a document.
4. **Envelope.** Every tool returns `{success:true, ...}` or `{success:false, code, error, detail?}` and never raises past the tool boundary.
5. **Tool-call caps are enforced on the node**; the client copies them for UX. Upload limits are enforced by the app: a file over a limit is excluded before it is sent, not ingested. The parser does not apply the templates' `parse_1.config.index.maxFileSize` (it reads the cap from a task configuration section the engine does not build from a `.pipe`; a phase-0 pin fails the day it does), and the engine does not enforce bytes written in this release.
6. **No reply carries a host, DSN, credential or tenant database name.** The live tool-path suite asserts this with the fixture values and a keyword regex over non-content fields.
7. **One similarity definition for visuals.** `sim` in `sample`, `project` and `neighbors` is recomputed from raw vectors by the store's metric in `vx_math.similarity`; the driver's own `score` is reported separately and labelled by `dialect.score`.
8. **Writes are gated on the node and the gate fails closed** (§6).
9. **Raw vectors leave the node only through `vectors` (≤2 keys).** Positions come from server-side PCA. A `vectors` answer exceeds the 2 KB tool-trace window (`dc:58,77-90`); when a run is traced its first 2 KB persist in the run log and the README's privacy paragraph says so.
10. **Agent catalogs do not change.** Explorer tools are DAP-only (`audience`, §4.0). The six legacy tools keep their descriptors (`inputSchema`, `description`, `outputSchema`, as `_build_tool_descriptors` builds them, `flt:1141-1190`) byte-identical, and keep their legacy output keys and semantics; every extension is additive. An agent sees exactly today's six descriptors.
11. **Pooler-safe SQL.** Every pgvector read or write is self-contained in one transaction: session-level `SET` is never used, because the managed store reaches tenant databases through a transaction-mode pooler (`nodes/scripts/tasks.js:94-97`; the live suites run a second pass through PgBouncer with `pool_mode = transaction`).

---

## 2. `DocumentStoreBase` extension (`ds`, after line 111; new modules beside it)

New files in `packages/ai/src/ai/common/store/`: `errors.py` (`StoreUnsupported`, `StoreError`, `ToolRefusal`), `vx_types.py`, `vx_math.py`, `vx_sample_cache.py`, `vx_tools.py` (the explorer tool methods, mixed into `VectorStoreToolMixin`), `vx_write_gate.py`, `vx_defaults.py` (`VECTOR_ALLOW_WRITES_DEFAULT = False`, `VECTOR_AGENT_WRITES_DEFAULT = True`), `pgvector/` (`driver.py`, `pool.py`, `sql.py`).

### 2.1 Types (`vx_types.py`)

```python
Deleted = Literal['active', 'deleted', 'all']
Key = Tuple[str, int]                       # (objectId, chunkId)

@dataclass(frozen=True)
class StoreInfo:
    backend: str                            # 'pgvector'|'qdrant'|'chroma'|'milvus'|'weaviate'|'pinecone'|'astra'|'atlas'
    backend_version: Optional[str]
    collection: Optional[str]               # collection/table name, never the database name; None when absent
    collection_exists: bool
    control_record: Optional[bool]          # None when the collection does not exist
    meta_column: Optional[bool]             # pgvector only: False while the ALTER is pending; None elsewhere
    metric: Optional[str]                   # 'cosine'|'l2'|'ip'|None
    dimension: Optional[int]
    model: Optional[str]
    index: Optional[Dict[str, Any]]
    size_bytes: Optional[int]
    caveats: List[str]

@dataclass(frozen=True)
class DocumentRow:
    objectId: str; path: str; chunks: Optional[int]; has_first_chunk: bool; deleted: bool
    tables: Optional[int]; nodeId: Optional[str]; size: Optional[int]
    modifyTime: Optional[int]; ingestedAt: Optional[str]; pointId: Optional[str]

@dataclass(frozen=True)
class DocPage:
    items: List[DocumentRow]; next_cursor: Optional[str]; total: Optional[int]
    counts_exact: bool; distinct: bool; sorted: bool; caveats: List[str]

@dataclass(frozen=True)
class ChunkPage:
    docs: List[Doc]; has_more: bool; next_after: int          # docs never carry embeddings

@dataclass(frozen=True)
class KnnGraph:
    k: int; offsets_row: np.ndarray; cols: np.ndarray; sims: np.ndarray; source: str   # 'native'|'node'
```

### 2.2 Hooks (all non-abstract; defaults in the base)

```python
class DocumentStoreBase(ABC):
    # existing abstract API unchanged: count_documents, searchKeyword, searchSemantic, get, getPaths, addChunks, remove, markDeleted, markActive, render

    def capabilities(self) -> FrozenSet[str]: ...   # introspection (type(self).hook is not DocumentStoreBase.hook) plus driver constants

    # Default: control record via doesCollectionExist() (ds:429-442), configured similarity; version/index/size None. Never raises for a missing collection.
    def describe(self) -> StoreInfo: ...
    def scoreInfo(self) -> Dict[str, Any]: ...      # default {'formula':'unknown','higher_is_better':True,'floor':0.2,'threshold':self.threshold_search}

    # docFilter.minScore when set (may be -inf), else the driver's legacy floor. Agents never set minScore: unchanged results.
    def effectiveFloor(self, docFilter: DocFilter) -> float: ...

    def countChunks(self, docFilter: DocFilter) -> Optional[int]: ...      # default None
    def countDocuments(self, docFilter: DocFilter) -> Optional[int]: ...   # distinct objectIds; default None

    # Default (distinct=False, sorted=False): get(DocFilter(chunkIds=[0], deleted=deleted, limit=limit+1, offset=cursor.offset)),
    # sorted by (parent, objectId) within the page; chunks=None; counts_exact=False; total=None.
    # The opaque cursor is {'o': offset, 'f': first key of the previous page}. When a page's first key equals cursor['f'],
    # the backend ignored the offset: the page ends with next_cursor=None and caveat 'documents_paging_unsupported'.
    # A native override validates its own cursor and raises invalidCursor() for one it did not issue (the tool answers
    # INVALID_INPUT 'cursor must be the next_cursor of a previous page.'); invalidCursor and defaultCursorState are
    # exported by document_store. A plain ValueError from the hook stays STORE_ERROR.
    def listDocuments(self, *, cursor: Optional[str], limit: int, object_ids: Optional[Sequence[str]], deleted: Deleted, sort: str) -> DocPage: ...

    # Default: get(DocFilter(objectIds=[objectId], minChunkId=after_chunk+1, maxChunkId=after_chunk+limit, deleted=deleted)) sorted by chunkId.
    def scrollChunks(self, objectId: str, *, after_chunk: int, limit: int, deleted: Deleted) -> ChunkPage: ...

    # (docs WITH embeddings, strategy_used in {'random','stratified','first'}). strategy='stratified' is native where cheap
    # (pgvector ROW_NUMBER() OVER (PARTITION BY objectid ORDER BY random()); Atlas $sample per $group) and otherwise raises
    # StoreUnsupported so the base sampler falls back (§2.4). Default: raise StoreUnsupported.
    def sampleChunks(self, *, n: int, seed: int, strategy: str, docFilter: DocFilter, include_keys: Sequence[Key]) -> Tuple[List[Doc], str]: ...

    # Vectors by key, BY FILTER (objectId IN ... AND chunkId IN ..., paired client-side, deleted='all'). A driver with deterministic
    # ids may try retrieve/get/fetch(ids=[uuid5(NAMESPACE_URL, f'{objectId}#{chunkId}')]) first and MUST fall back to the filter
    # for every miss (legacy rows have uuid4 ids). Each Doc carries metadata.pointId. Default: raise StoreUnsupported.
    def getVectors(self, keys: Sequence[Key]) -> List[Doc]: ...

    # kNN graph over the sampled keys. Default: vx_math.knn over the cached vectors (source='node'). Qdrant: search_matrix_offsets(
    # sample=len(keys), limit=k, query_filter=has_id(pointIds)) (source='native'; qdrant_client.py:657) up to 500 keys.
    def knnGraph(self, keys: Sequence[Key], vectors: np.ndarray, metric: str, k: int) -> KnnGraph: ...

    # Rows actually removed. Default: n = countChunks(DocFilter(objectIds=ids, deleted='all')); self.remove(ids); return n.
    def removeCounted(self, objectIds: List[str]) -> Optional[int]: ...

    @staticmethod
    def resolveDeleted(docFilter: DocFilter) -> Deleted: ...   # docFilter.deleted if set, else isDeleted None/False -> 'active', True -> 'all'
```

`capabilities()` returns the hooks named in the class constant `DocumentStoreBase.VX_HOOKS` that the driver overrides, plus the names in the class constant `DocumentStoreBase.VX_DRIVER_CAPABILITIES`: an empty frozenset in the base, which a driver overrides with what its backend does natively beyond the hooks (such as `sample_stratified_native`, `knn_native`, `documents_distinct`, `documents_sorted` or `search_keyword`; the vocabulary is `vx_types.CAPABILITY_KEYS`).

Base-class changes that ride along: `doesCollectionExist(modelName)` **keeps today's read-path behaviour** (never refuses on model); the comparison is exposed as `describe().caveats` `model_mismatch` and `dialect.health.model_mismatch`, and `search` adds `warnings:['model_mismatch']`. `BaseException` for non-zero offsets (`qdrant.py:404`, `chroma.py:536`, `milvus.py:365`, `weaviate.py:404`, `pinecone.py:278`) becomes `ValueError`. **The control-record path is untouched:** `createCollection` keeps calling `self.addChunks([doc], checkCollection=False)` (`ds:535`); no driver refuses `schema` inside `addChunks`.

### 2.3 Schema changes (`packages/client-python/src/rocketride/schema/`)

- `DocFilter` gains `deleted: Optional[Literal['active','deleted','all']] = None` and `minScore: Optional[float] = None`.
- `DocMetadata(pInstance)` defaults (`dm:126-139`) gain extras `size`, `modifyTime` (from `Entry`) and `ingestedAt` (UTC ISO-8601) (`VX_METADATA_EXTRAS`). Stored as payload by Qdrant/Chroma/Weaviate/Milvus, in `meta jsonb` by pgvector when the column exists, dropped by Astra/Atlas, null in `documents` when absent. `DocumentStoreBase.__init_subclass__` routes every driver's `addChunks` through `vxWritableChunks()`, which hands a driver copies without the extras unless `vxStoresExtras()` is true: the class constant `VX_STORES_EXTRAS` when the driver sets it (pgvector sets `True`), else false for the pgvector backend and the column-per-key drivers and true for the payload stores. A driver whose backend refuses unknown keys sets `False`.
- `QuestionText.__str__` returns `self.text` (`q:270-285`); drivers also read `query.text` explicitly.

### 2.4 Numpy helpers (`vx_math.py`, pure, golden-tested with fixed seeds)

```python
def similarity(metric, A, B, block=512) -> np.ndarray             # cosine: normalised dot; ip: dot; l2: 1/(1+d)
def pca(X, k=3) -> (coords, explained_variance_ratio, mean, basis) # float32 SVD; sign fixed: largest |loading| positive
def knn(metric, X, k) -> (offsets_row, cols, sims)                 # Qdrant offsets shape, exact, blocked
def density(offsets_row, sims) -> np.ndarray
def outliers(dens, pct=1.0) -> List[int]
def duplicates(offsets_row, cols, sims, threshold=0.97) -> List[Tuple[int,int,float]]
def stratified_pick(rows_by_doc: Dict[str, List[Key]], n, seed, pinned) -> List[Key]   # pinned, then lowest chunk of every doc, then round-robin
def knn_overlap(offsets_row, cols, positions, k=15) -> float       # layout-quality metric
```

**Sampling algorithm (`vx_tools.sample`).** (1) Pin `include_keys`. (2) If the driver's `sampleChunks('stratified')` is native, take the remainder from it (`strategy_used='stratified'`, `biased:false`). (3) Otherwise, when `listDocuments` returned exact `chunks`, synthesise `(objectId, 0..chunks-1)` for ≤500 documents, run `stratified_pick`, and read through `getVectors`; **every miss** (non-contiguous ids, chunk-0-less documents) is refilled from `sampleChunks('random')`, else `'first'`, until `n` real rows or the collection is exhausted; the answer reports the actual `n`, `strategy_used` of the fill and `biased:true` when any refill happened. (4) Without counts: pin the chunk-0 row of every listed document (≤500) and fill as in (3). Pinned by mock-driver tests with chunk ids {3,7,64} and with `chunks=None`.

### 2.5 Sample cache (`vx_sample_cache.py`)

Per store instance: LRU of 2 entries, 600 s TTL, keyed by `sample_id = 's-<seed>-<8 hex of sha1(keys)>'`, holding `keys`, float32 vectors, PCA mean/basis, metric, dimension, mode, pointIds. One `threading.Lock` per instance: a second `sample`/`project` while one runs answers `BUSY`. Light mode refused above 2,000 points when `dimension × n × 4 > 64 MB` (`LIMIT_EXCEEDED`).

---

## 3. Per-driver implementation notes (what each driver overrides)

| Driver | describe | counts | listDocuments | scrollChunks / getVectors | sampleChunks / knnGraph | removeCounted | Repairs bundled |
|---|---|---|---|---|---|---|---|
| **pgvector**: `store_postgres` + `rocketride_vector` via `ai.common.store.pgvector.driver.PgVectorStore` | catalog (`format_type(atttypmod)`, `pg_indexes`, `pg_total_relation_size`, `SHOW server_version`, `to_regclass`, `information_schema.columns` for `meta`) | `COUNT(*) WHERE`; `COUNT(DISTINCT objectid)` | a page's keys from `GROUP BY objectid` over `min(parent)` alone (keyset cursor `(path, objectId)`), then `COUNT(*)`, `bool_or(chunkid=0)`, `bool_or(isdeleted)`, `COUNT(*) FILTER (WHERE istable)` and `(array_agg(meta ORDER BY chunkid))[1]` (omitted when no `meta` column) for that page's objectIds only; the total is counted on the first page and carried in the cursor; `distinct=True`, `sorted=True` | `ORDER BY chunkid OFFSET`; `WHERE objectid = ANY(%s) AND chunkid = ANY(%s)` → `.tolist()` | ordered by a seeded hash of each row's id (`hashtextextended(id::text, seed)`), so nothing is set for the session (`setseed` would leak to the next client of a transaction pooler): stratified native (each document's rows ranked chunk 0 first, then by one hash; the ranks taken in the order of a second, independent hash), random (one hash); knnGraph default | the `DELETE` row count | **D1** insert from a column allowlist (`TABLE_COLUMNS`) with `psycopg2.sql.Identifier`; unknown keys → `meta jsonb`. **Meta column:** `ALTER TABLE ... ADD COLUMN IF NOT EXISTS meta jsonb` runs once at instance open in its own transaction with `SET LOCAL lock_timeout = '2s'`, never inside a batch write; on lock failure the instance writes without `meta` (extras dropped, caveat `extras_not_stored`, `health.meta_column:false`) and retries at most once per 60 s on later writes; reads tolerate a missing `meta`. **D2/D5** `ConnectionPool` (`ai.common.graph.connection_pool`), lazy, min 0, max 4, idle release 60 s; **every read transaction** runs, in order, `SELECT '[0]'::vector` (loads the extension library; no `LOAD`), `SET TRANSACTION READ ONLY`, `SET LOCAL statement_timeout`, `SET LOCAL hnsw.iterative_scan = relaxed_order`, the query, then commit/rollback in `finally`; writes under one lock in one transaction. **D6** stats via control record. **D8** `ORDER BY chunkid OFFSET` in `get`. `getPaths` excludes `schema`/deleted, `ORDER BY parent`. Keyword on `query.text`. Floor via `effectiveFloor`. A NULL `isdeleted` reads as active. Re-ingest delete only in the batch holding chunk 0. New tables get an `(objectid, chunkid)` index and, up to 2,000 dimensions, an HNSW index; every write transaction first takes the table's advisory lock (`pg_advisory_xact_lock`). An index name longer than 63 characters becomes `<prefix>_<digest>_<suffix>` (8 hex of the table name's SHA-1), so two long tables never share one. The extras go to `meta` (`VX_STORES_EXTRAS = True`). Before pgvector 0.8 there is no iterative HNSW scan and `describe()` adds the caveat `filtered_search_may_underfill`. `rocketride_vector` joins `StoreGlobalBase`/`StoreInstanceBase`, `classType ['store','tool']`, `capabilities ['invoke']`, `rrvector.allow_writes` (it gains tools only together with the write gate). **Legacy table shape** (seeded for the live suites): old DDL + `signature text`, no `meta`, serial ids, hand-inserted control row, one document missing chunk 0. |
| **qdrant** | `get_collection` | `count(exact=True)`; documents = `count(chunkId==0 ∧ isDeleted==false ∧ objectId≠schema)` with caveat `documents_by_first_chunk` | scroll chunk-0 with `next_page_offset` cursor (`sorted=False`), `facet(key='meta.objectId', facet_filter objectId∈page, exact=True)` for counts; orphan sweep `facet(limit=1000)` minus the chunk-0 set (`has_first_chunk=False`; above 1,000 → `document_count_capped`) | `scroll(order_by='meta.chunkId')`; `retrieve(ids=[uuid5...], with_vectors=True)` fast path, filter scroll for misses | `query_points(query=SampleQuery(sample=Sample.RANDOM), with_vectors=True)` → `'random'`; **knnGraph native** via `search_matrix_offsets` (`knn_source:'native'`) for samples of at most 500 points (`Store.NATIVE_KNN_MAX`); a larger sample, or a native failure, gets the node's graph (`knn_source:'node'`), so the app reads `knn_source` per sample, not `capabilities.knn_native` | count then delete by filter | offset-as-point-id → cursor; deterministic ids for new writes; `parent` `MatchValue`; non-zero offset → `ValueError`; floor; `exact=True` kept (caveat `brute_force_search`); Dot scores `(1 + dot) / 2` (was a sigmoid of `dot / 100`, which put every result near 0.5), `scoreInfo.range` null for Dot. |
| **chroma** | `metadata['hnsw:space']`, `count()` | `len(get(where, include=[])['ids'])` (O(N), cached per §4.2 `stats`); documents None | `get(where={'chunkId':0}, include=['metadatas'], offset, limit)` + one `get(where objectId $in page, include=[])`; `sorted=False` | native offset; `getVectors` by `$and` filter with `include=['embeddings','metadatas']` | random offset page → `'first'`; knnGraph default | count then delete | score `(d+1)/2` → `(2-d)/2`; floor; objdir key (`:586`); `render` (`:797`); `markDeleted`/`markActive` (`:721,745`); `isTable=False` (`:398`); tri-state; deterministic ids. |
| **milvus** (mock) | `describe_collection`, `describe_index` | `count(*)` with filter; documents None | chunk-0 `query(offset, limit)` + per-page counts; `sorted=False` | native; by filter | default | count then delete | `meta: model_dump(exclude_none=True)` (`:506`); `render` (`:662`); quoted filters (`:203-213`); keyword on text; chunk-0-batch delete; L2 sigmoid → `1/(1+d)`; driver stops applying the node threshold. |
| **weaviate** (mock) | `config.get()` | `aggregate.over_all(total_count=True)`; documents via `GroupByAggregate` | `GroupByAggregate(prop='objectId')` + chunk-0 fetch; `sorted=False` | `fetch_objects(include_vector=True, after=uuid)`; by filter | uuid order → `'first'` | count then `delete_many` | objdir `TypeError` (`:459`); inversion (`:321`); floor; keyword; offset (`:431`); every-call delete; uuid5 keyed ids. |
| **pinecone** (mock, cloud) | `describe_index` | None; None | `fetch_by_metadata(filter={'chunkId':0}, limit≤1000, pagination_token)`; `sorted=False` | token paging; `fetch(ids)` fast path, filter for misses | serverless `list`+`fetch` → `'first'`; pod → UNSUPPORTED | None | `get` top_k ≤1000 paged; None metadata; `threshhold_search` typo; keyword → UNSUPPORTED; every-call delete; tri-state. |
| **astra** (mock, cloud) | `collection.definition()` | `count_documents(filter, upper_bound=1000)`; documents None | chunk-0 `find` + per-page counts; `sorted=False` | `find(sort chunkId, projection={'$vector':True})`; by filter | default | count then `delete_many` | `aggregate` AttributeError (`:346`); `meta` dump (`:425`); `upper_bound` (`:248`); offset (`:312`); floor. |
| **atlas** (mock, cloud) | `list_search_indexes` | `count_documents`; `$group` | `$group` + `$skip/$limit`, `$sort` by path → `sorted=True` | `find` skip/limit; by filter | `$sample` → `'random'`; stratified native (`$sample` per group) | `deleted_count` | double-normalised score (`:543`); floor; `meta` dump (`:348`); `knnVector` caveat; `UnboundLocalError` (`:268-275`); info logging removed. |
| **elasticsearch/opensearch** | out of v1 (no mixin); never a card | | | | | | |

`support` per provider (reported by `dialect`): `postgres`, `rocketride_vector`, `qdrant`, `chroma` = `'supported'` once their **unmocked** live suite passes on both a new and a legacy collection (and, for the two pgvector providers, under the pooler pass); `milvus`, `weaviate`, `pinecone`, `astra_db`, `mongodb+srv` = `'experimental'`. The value is the driver's class constant `DocumentStoreBase.VX_SUPPORT` (base default `'experimental'`, for which `dialect` also adds the `experimental` caveat); a driver sets `'supported'` only on that evidence. **A mocked `services.json` case or a mock-driver unit test never flips `support`**.

**Mocks.** `nodes/test/mocks/` shadows every store client engine-wide under `ROCKETRIDE_MOCK` (`nodes/scripts/tasks.js:196-215`). A driver change that uses a new native client call adds it to the mock of that client (`psycopg2.sql` with `Identifier`/`SQL`/`Composed`; qdrant `facet`, `count`, `retrieve`, `search_matrix_offsets`, `SampleQuery`; chroma `get(include=['embeddings'])`; etc.). A mock change is paired with the same assertion in the unmocked suite where one exists.

**Legacy collections.** Written by today's drivers: uuid4 point ids, chunk 0 missing for some documents, no `size`/`modifyTime`/`ingestedAt`, no `meta` column on pgvector. Every hook works on them.

---

## 4. Tools on `VectorStoreToolMixin` (`vx_tools.py`, mixed in; `ds:657` keeps its name)

### 4.0 Wrapper and audience

```python
def vectordb_tool(fn):  # applied under @tool_function on every tool, new and legacy
    # 1. args = _normalize_vectordb_tool_input(args) (ds:603-654)
    # 2. try: return fn(self, args)
    #    except StoreUnsupported as e: {'success': False, 'code': 'UNSUPPORTED', 'error': str(e)}
    #    except ToolRefusal as e:      {'success': False, 'code': e.code, 'error': e.message, **e.extra}
    #    except (KeyboardInterrupt, SystemExit): raise
    #    except BaseException as e:    {'success': False, 'code': 'STORE_ERROR', 'error': f'{type(e).__name__}: {e}'}
    # 3. post-process: numpy -> list, float rounding (5 dp scalars, 4 dp bulk, 2 dp light), size assertion vs LIMITS
```

A `STORE_ERROR` message is scrubbed before it leaves the node: URLs, DSNs, `user:pass@host`, bearer tokens, API keys, `key=value` and `key: value` secrets, quoted user, role, database, relation, schema and tenant names, "to/for tenant|database X", IP addresses, `host:port` and DNS names are removed. A connection, DNS, TLS or authentication failure (stdlib connection errors, the client libraries' connection and auth errors, HTTP 401/403/407, Milvus code 2, MongoDB auth codes, gRPC unavailable and authentication status codes, psycopg2/psycopg `OperationalError` and `InterfaceError`, following `__cause__` and `__context__`) answers the fixed sentence "The store could not be reached or refused the credentials; see the engine log." and the scrubbed text goes to the engine log only. An answer that cannot be serialised is a `STORE_ERROR`.

`@tool_function` (`flt:67-94`) gains `audience: Tuple[str, ...] = ('agent', 'dap')` stored in `__tool_meta__`; `_build_tool_descriptors` (`flt:1141-1190`), called from `tool.query` with `audience='agent'`, lists only tools whose audience includes it; `tool.invoke` dispatches every `@tool_function` regardless. The six legacy tools keep the default audience and their descriptors byte-identical. Every new tool and `embed` is `audience=('dap',)`. `test_tool_audience.py` (the `packages/ai` suite, `./builder ai:test`) asserts: the agent catalog (`host.py:93-123` descriptors) is byte-identical before and after; legacy inputs of `search`/`stats`/`delete`/`get`/`objdir`/`upsert` are accepted; legacy output keys are present with legacy semantics, including `stats` on a missing collection answering `{success:true, count:0, model:'', vector_size:0}`.

### 4.1 Codes, capabilities, caveats, limits

Codes: `INVALID_INPUT`, `UNSUPPORTED`, `NOT_FOUND`, `RESERVED_ID`, `COLLECTION_MISSING`, `STORE_ERROR`, `DIMENSION_MISMATCH`, `MODEL_MISMATCH`, `NO_EMBEDDER`, `LIMIT_EXCEEDED`, `SAMPLE_EXPIRED`, `BUSY`, `TIMEOUT`, `RATE_LIMITED`, `WRITES_DISABLED`, `WRITES_SOURCE`, `WRITES_PUBLIC`, `WRITES_BROADCAST`, `WRITES_AGENT`, `WRITES_UNKNOWN_CALLER`.

Capabilities (`dialect.capabilities`): `describe`, `count`, `count_documents`, `documents`, `documents_distinct`, `documents_sorted`, `chunks`, `vectors`, `sample`, `sample_light`, `sample_stratified_native`, `knn_native`, `project`, `neighbors`, `search_vector` (always true), `search_keyword`, `remove`, `remove_count`, `soft_delete` (false in v1), `embed_node` (filled by the app); `projection: ['pca']`.

Caveats: `brute_force_search`, `no_filtered_count`, `biased_sample`, `score_scale_raw`, `score_scale_inverted_fixed`, `shared_org_table`, `experimental`, `cloud_only_unverified`, `extras_not_stored`, `documents_by_first_chunk`, `document_count_capped`, `documents_unsorted`, `documents_paging_unsupported`, `model_mismatch`, `meta_column_pending`, `filtered_search_may_underfill` (pgvector older than 0.8, which has no iterative HNSW scan: a filtered search may return fewer than `k` rows).

Limits (node-enforced; reported in `dialect.limits`):

| Key | Default / max |
|---|---|
| `documents_page` | 200 / 500 |
| `chunks_page` | 100 / 200 |
| `vectors_keys_max` | 2 |
| `sample_default` / `sample_max` / `sample_max_light` | 1,000 / 2,000 / 5,000 (light: `include_text:false`, `knn_k ≤ 10`, 2-dp floats) |
| `snippet_chars` | 120 (word boundary, ellipsis) |
| `knn_k_max` | 30 (10 in light mode) |
| `neighbors_k_max` | 50 (default 12) |
| `project_keys_max` | 200 |
| `scope_keys_max` | 2,000 |
| `top_k_max` | 100 |
| `write_ids_max` | 100 |
| `sample_budget_ms` | 60,000 |
| `statement_timeout_ms` | 30,000 (pgvector; others null) |
| `counts_cached_s` | 60 |
| `embed_texts_max` | 8; `embed_per_minute` 30, burst 5 |

### 4.2 Tool table

Every input goes through the wrapper; every output has `success`. `key` is always `[objectId, chunkId]`. Server-side filters are `object_ids` only.

**`dialect`** (new; the shared library's default probe) — `{}` → always a success envelope when the node is up:
```json
{"success":true,"dialect":"vector","contract":"vector/1","provider":"postgres","backend":"pgvector","backend_version":"0.8.0",
 "collection":"vx_demo_docs","metric":"cosine","model":"sentence-transformers/all-MiniLM-L6-v2","dimension":384,
 "index":{"type":"hnsw","params":{"m":16,"ef_construction":64}},
 "score":{"formula":"1 - cosine_distance","range":[-1,1],"higher_is_better":true,"floor":0.2,"threshold":0.3},
 "support":"supported","allow_writes":true,"agent_writes":true,"writes_scope":"tools_source",
 "write_tools":["remove_document","delete","upsert"],
 "capabilities":{"describe":true,"count":true,"count_documents":true,"documents":true,"documents_distinct":true,"documents_sorted":true,"chunks":true,"vectors":true,"sample":true,"sample_light":true,"sample_stratified_native":true,"knn_native":false,"project":true,"neighbors":true,"search_vector":true,"search_keyword":true,"remove":true,"remove_count":true,"soft_delete":false,"projection":["pca"]},
 "limits":{"documents_page":500,"chunks_page":200,"vectors_keys_max":2,"sample_default":1000,"sample_max":2000,"sample_max_light":5000,"snippet_chars":120,"knn_k_max":30,"neighbors_k_max":50,"project_keys_max":200,"scope_keys_max":2000,"top_k_max":100,"write_ids_max":100,"sample_budget_ms":60000,"statement_timeout_ms":30000,"counts_cached_s":60},
 "health":{"collection_exists":true,"control_record":true,"model_mismatch":null,"meta_column":true},
 "caveats":[]}
```
A missing collection answers the same envelope with nulls and `health.collection_exists:false`, `health.control_record:null`; `health.control_record:false` → "Repair needed"; `health.meta_column:false` → caveat `meta_column_pending`. Only `STORE_ERROR` is a failure envelope. Never includes host, port, DSN or database name.

**`stats`** (legacy descriptor unchanged; answer extended) — `{"mode":"full"}` (default) or `{"mode":"quick"}` → `{"success":true,"count":1319,"model":"…","vector_size":384,"collection_exists":true,"documents":42,"documents_without_first_chunk":1,"chunks":1318,"deleted_chunks":0,"raw_count":1319,"tables":3,"avg_chunks_per_document":31.4,"dimension":384,"metric":"cosine","computed_at":"2026-10-08T18:31:03Z","counts_as_of":"2026-10-08T18:30:40Z"}`. `count` keeps today's semantics (`count_documents()`); `model`/`vector_size` are loaded from the control record first (D6). **A missing collection keeps the legacy success envelope** `{success:true, count:0, model:'', vector_size:0, collection_exists:false}` with the extended keys null. `documents = countDocuments(active)` where supported, else `countChunks(chunkIds=[0], active)` with caveat `documents_by_first_chunk`; `chunks`, `deleted_chunks`, `tables` from `countChunks`; null where unsupported. **Filtered counts are cached per instance for `counts_cached_s`.** `mode:'full'` always recounts; `mode:'quick'` returns the raw `count` plus the cached figures with `counts_as_of` while they are at most `counts_cached_s` old, and recounts once they are older. Any write through the driver (`addChunks`, `remove`, `markDeleted`, `markActive`, so the data lane's uploads too) drops the cached figures.

**`documents`** (new) — `{"cursor":null,"limit":200,"object_ids":null,"deleted":"active","sort":"path"}` → `{"success":true,"items":[{"objectId":"060f…","path":"C:/demo/field/kestrel_field_guide.md","chunks":2,"has_first_chunk":true,"tables":0,"deleted":false,"nodeId":"chunk_1","size":7419,"modifyTime":null,"ingestedAt":"2026-10-08T18:20:11Z","pointId":"a3f…"}],"next_cursor":"eyJvIjoy…","total":42,"counts_exact":true,"distinct":true,"sorted":true,"caveats":[]}`. A list, never a dict. `sorted:false` → the client sorts loaded rows (caveat `documents_unsorted`); a repeated page ends the listing with `documents_paging_unsupported`. `limit` > max → clamped with `warnings:["limit_clamped"]`.

**`chunks`** (new) — `{"object_id":"060f…","after_chunk":-1,"limit":100,"deleted":"active"}` → `{"success":true,"items":[{"chunkId":0,"content":"…","length":3702,"isTable":false,"tableId":0,"isDeleted":false,"pointId":"a3f…","metadata":{…}}],"has_more":true,"next_after":99,"total":112}`. Never calls `render`. **Never returns vectors.** `NOT_FOUND` for `schema` or an unknown id. `{"object_id": X, "limit": 1}` is the app's existence probe.

**`vectors`** (new) — `{"keys":[["060f…",0],["9fa0…",0]]}` (≤2) → `{"success":true,"items":[{"key":["060f…",0],"pointId":"a3f…","dimension":384,"norm":1.0,"values":[…]}],"model":"…"}`. The single path that returns raw vectors.

**`sample`** (new) — `{"n":1000,"seed":7,"strategy":"stratified","mode":"detailed","include_keys":[["060f…",0]],"filter":{"object_ids":null},"deleted":"active","knn_k":15,"components":3,"duplicate_threshold":0.97,"include_text":true}` →
```json
{"success":true,"sample_id":"s-7-a1b2c3d4","expires_in_s":600,"n":1000,"n_requested":1000,"mode":"detailed","of":{"chunks":1318,"documents":42},"strategy_used":"stratified","biased":false,"knn_source":"node","metric":"cosine","dimension":384,
 "docs":[{"i":0,"objectId":"060f…","path":"C:/demo/field/kestrel_field_guide.md","chunks":2,"in_sample":2}],
 "points":{"doc":[0,0,1],"chunk":[0,1,0],"x":[…],"y":[…],"z":[…],"len":[3702,3714,…],"snip":["Kestrel field guide …"],"pinned":[1,0,0]},
 "knn":{"k":15,"offsets_row":[…],"cols":[…],"sims":[…]},
 "density":[…],"outliers":[311,5],"duplicates":[{"a":12,"b":87,"sim":0.991}],
 "pca":{"explained":[0.21,0.13,0.08]},"took_ms":420}
```
`snip` ≤ `snippet_chars`. `mode:'light'`: `n ≤ sample_max_light`, no text, `knn_k ≤ 10`, 2-dp floats. Server side: §2.4 sampling, PCA, `knnGraph` (native on Qdrant), density, outliers, duplicates. Columnar JSON; the node test asserts ≤1 MB at n=2,000/k=15 detailed and n=5,000/k=10 light **on a corpus whose chunks are ≥3,000 characters**, and ≤1.1 MB at n=2,000 with `knn_k_max` (30; about 1.03 MB). `outliers` is empty below 10 points and when every density is the same. Errors: `UNSUPPORTED`, `BUSY`, `TIMEOUT`, `LIMIT_EXCEEDED`, `COLLECTION_MISSING`.

**`project`** (new) — exactly one of `vector` or `keys`: `{"sample_id":"…","vector":[…],"m":10,"with_similarities":true}` or `{"sample_id":"…","keys":[["9fa0…",3]],"m":10}` → `{"success":true,"items":[{"key":null,"in_sample":null,"pca":[…],"neighbors":[{"i":12,"sim":0.83}]}],"similarities":[…],"dimension":384}`. Errors: `SAMPLE_EXPIRED`, `DIMENSION_MISMATCH`, `NOT_FOUND`, `INVALID_INPUT`.

**`neighbors`** (new) — `{"key":["060f…",0]}` or `{"vector":[…]}`, plus `"k":12,"exclude_self":true,"filter":{"object_ids":null},"scope_keys":null` → `{"success":true,"items":[{"key":["9fa0…",3],"sim":0.83,"score":0.83,"below_floor":false,"path":"…","chunkId":3,"preview":"…"}],"metric":"cosine","scope":"collection","k_requested":12}`. Whole-collection `searchSemantic(..., DocFilter(limit=k+1, minScore=-inf))`. With `scope_keys` (≤2,000): `{"success":true,"scores":[…]}`. One in flight per instance (`BUSY`).

**`search`** (legacy descriptor unchanged; additive) — legacy input keeps today's behaviour and gains `success:true`, `rank`, `warnings` (e.g. `["keyword_fallback","<semantic error>"]`, `["model_mismatch"]`) and `mode_used`. DAP extension: `{"vector":[…],"embedding_model":"…","mode":"auto|semantic|keyword","filter":{"objectIds":[…],"isTable":false,"minChunkId":0,"maxChunkId":99},"deleted":"active","include_below_floor":true,"include_below_threshold":true}` → results add `raw_score`, `sim`, `below_threshold`, `below_floor`. `query` without a bound embedder → `NO_EMBEDDER`; wrong length → `DIMENSION_MISMATCH`; `mode:'keyword'` on Pinecone → `UNSUPPORTED`. Results sorted by `score` desc when `vector` is given.

**`remove_document`** (new, write, gated, DAP-only) — `{"object_ids":["060f…"]}` (1–100) → `{"success":true,"removed":[{"objectId":"060f…","chunks_removed":2}],"not_found":["…"],"removed_chunks":2,"audit":{"action":"vector.remove_document","node":"store_1","provider":"postgres","collection":"vx_demo_docs","object_ids":["060f…"],"rows":2,"caller":{"auth":"account","userId":"…","teamId":"…"}}}`. `RESERVED_ID` for `schema`. The `audit` block never carries content or vectors.

**`delete`** (legacy descriptor unchanged, gated) — unchanged input → `{"success":true,"deleted_count":3,"removed_chunks":2,"not_found":["…"]}`.

**`upsert`** (legacy descriptor unchanged, gated) — unchanged input/output; an external caller supplying `embedding`/`embedding_model` → `INVALID_INPUT`; `object_id == 'schema'` → `RESERVED_ID`. Into an existing collection built with another embedding model it answers `MODEL_MISMATCH`, with another dimension `DIMENSION_MISMATCH`, before anything is written. For all three write tools the gate (§6.3) runs before the input is checked, so a refused caller sending too many ids or a malformed list gets the gate's code, not `INVALID_INPUT`.

**`get`, `objdir`** (legacy descriptors unchanged; fixed) — `get` guards `int()`, clamps `limit`, pages in chunk order, adds `has_more`; `objdir` keeps `paths`, adds `entries`, excludes `schema` and deleted rows, clamps `limit`.

### 4.3 `embed` on the embedding nodes (new mixin `packages/ai/src/ai/common/embed_tool.py`)

`{"texts":["…"],"kind":"query"}` (1–8 texts, each ≤8,000 chars) → `{"success":true,"model":"…","dimension":384,"vectors":[[…]],"prefix_applied":null,"ms":12}`. Token bucket per task: 30/min, burst 5 → `RATE_LIMITED` with `retry_after_s`. The mixin owns `IGlobal.embed_lock`; the tool and the flush path (`embedding_transformer/IInstance.py:83-102`, `embedding_openai/IInstance.py:52-59`) both acquire it. `audience=('dap',)`. Reachability from the tools token is pinned by a phase-0 test (`scripts/acceptance/vector-explorer/phase0/`).

- `kind:'query'` encodes like the `questions` lane (query prefix), `'document'` like the `documents` lane; vectors are rounded to 6 decimals; `ms` includes any wait for the lock.
- `IGlobal.embed_lock` is a shared/exclusive lock that prefers the exclusive side: the node's own batches hold it shared, an `embed` call exclusively, so a call waits for the batches already on the model and new batches queue behind it. It covers the model call only, not the write that follows a flush. A call still waiting after 60 s answers `BUSY` and its token is refunded.
- The token bucket lives on `IGlobal.embed_bucket`; a call refused before it reaches the model (`INVALID_INPUT`, `NO_EMBEDDER`, `BUSY`) spends no token. Blank texts are `INVALID_INPUT`.
- A model failure is a `STORE_ERROR` whose message names only the exception type; the full text goes to the engine log.

---

## 5. Pipeline shape the contract assumes (the "VX shape")

```
ingest_1 (dropper) ─tags→ parse_1 ─text→ chunk_1 ─documents→ embed_1 ─documents→ store_1   [control: tools_1]
chat_1   (chat)    ─questions──────────────────────────→ embed_1 ─questions→ store_2 ─questions→ llm_1 ─answers→ response_1
                                                                                store_2 ─documents→ response_2 (response_documents)
tools_1  (tools)   ─control(tool)→ store_1, embed_1
```

- `store_1`/`store_2`: two instances of the same provider and collection; this avoids the `stack.cpp:337-345` rejection of a store that is both data-fed and drives a sub-pipeline. `store_2` keeps `allow_writes:false` and the app never lists it (`nodeFilter`, §8).
- Reachability from the tools token: `store_1`, `store_2`, `embed_1`, `llm_1`; `parse_1`/`chunk_1` are "not found in pipeline".
- Tool calls run on the anchor token (tools; chat or ingest in read-only mode). Ingest = `sendFiles` on the ingest token; chat = `chat` on the chat token.
- Degrade path (single-store pipelines): the app tries `embed` through the chat role's token with `nodeId`; if nothing reaches `embed_1`, map text queries are disabled with a reason.
- Chat answers carry `result_types.answers` and, through `response_2`, `result_types.documents`.
- Templates carry `llm_1.config.custom.apikey = 'replace-with-your-key'` and an empty `base_url`; `start_fixtures.py --llm stub` substitutes the local stub and renames the LLM component to "Local stub LLM". Templates pin `parse_1.config.index.maxFileSize = 52428800`; the engine does not apply it in this release (§1 rule 5).

---

## 6. Write gate

### 6.1 Switches (node config)
- `vector.allow_writes` — boolean, default `VECTOR_ALLOW_WRITES_DEFAULT` (`vx_defaults.py`, **false in this build**), "Allow document management from tool calls", defined once in `nodes/src/nodes/core/services.common.vector.json`; `rrvector.allow_writes` for rocketride_vector. Read in `StoreGlobalBase.beginGlobal` with `parse_bool`. The templates test and the toolpath expectation table import the same constant, so a reversal is one line.
- `vector.agent_writes` — boolean, default `VECTOR_AGENT_WRITES_DEFAULT` (true).
- Where they live: like the other `vector.*` fields, both are profile fields, so in a `.pipe` they sit on the store component at `config[config.profile].allow_writes` (for example `config.local.allow_writes`; `config.cloud.allow_writes` for rocketride_vector) and the node reads them from the merged `Config.getNodeConfig` result. An absent field means the default.
- Scope: `allow_writes` governs external DAP tool calls only. With the switch **on**, the gate still refuses callers on a public (`pk_`) task key, non-tools sources, broadcasts, caller-supplied embeddings and `schema`; with it **off** (the default), SDK scripts calling `upsert`/`delete` through `client.tool()` get `WRITES_DISABLED` (no in-repo script, doc or test does so today). Data-lane ingest is unchanged except for the reserved id (§6.3).

### 6.2 Call context (engine; `packages/ai/src/ai/common/tool_context.py`)

```python
@dataclass(frozen=True)
class ToolCallContext:
    origin: str                 # 'dap' | 'agent'
    source_type: Optional[str]  # provider of the calling task's source; None when unknown
    targeted: bool
    caller: Dict[str, Any]      # {'auth': 'public'|'task'|'account'|'agent'|'unknown', 'userId', 'teamId', 'orgId'}

TOOL_CONTEXT_FIELD = '__tool_context__'    # name of the plain instance attribute stamp_param() sets on the engine-built param
def current_tool_call() -> Optional[ToolCallContext]: ...
@contextmanager
def tool_call(ctx: ToolCallContext): ...
```

**The context rides on the invoke param; the dispatcher sets the ContextVar.**
1. `cmd_data.on_rrext_process` (`cmd_data.py:94-165`), for `subcommand == 'tool'`, overwrites `request['arguments']['caller']` with the server's view (`pk_` → `public`, `tk_` → `task`, else `account`), discarding anything the client sent.
2. `dc._tool` (`dc:985-1080`) builds the `IInvokeTool.Invoke` param from `tool_name` and `input` **only** and stamps it with `stamp_param(param, dap_context(source_type=..., node_id=node_id, caller=args['caller']))`. `source_type` is the provider of the component that `taskConfig.pipeline.source` names (`'tools'`, `'chat'`, `'dropper'`, ...), read from the task's own pipeline configuration; the target endpoint's logical type is not it (that is the pipeline's Null endpoint). `targeted` is whether the request named a node.
   The stamp is a plain instance attribute set with `setattr` on the param the engine built, so it never appears in `model_dump()` (which tracing serialises). `read_stamp` reads it only from the instance `__dict__`: a pydantic extra field of the same name (what `model_validate`, keyword construction, `model_construct`, `model_copy(update=...)` or `model_validate_json` make of client data) is ignored, and so is any dict op. `stamp_param` raises `TypeError` on a dict and drops a same-named extra field before stamping. A client cannot reach the stamp: nothing inside `input` is read by the gate.
3. The agent host (`host.py:206` Validate, `host.py:229` Invoke) stamps `ToolCallContext(origin='agent', source_type=None, targeted=True, caller={'auth':'agent'})` on the param it builds.
4. `IInstanceBase._dispatch_tool` (`flt:1232-1258`) reads the field and enters `tool_call(ctx)` around the method call. The method runs on the same thread as the dispatcher by construction, so no cross-hop assumption remains. (The C++ hop is inline on the calling thread as well: `cb_control` → `filter->control` → `callPython` = `LockPython` + direct call, `filter.callbacks.target.cpp:80-123`, `engLib/python/call.hpp:179-196`; a phase-0 probe pins it through the real engine.)
5. **Only the engine sets the context.** The DAP path stamps it from the server's own view of the call (steps 1 and 2) and the agent host stamps the params it builds (step 3); nothing a client sends can set or change it.
6. The mixin imports `current_tool_call` inside `try/except ImportError`; on an engine without `tool_context`, or a dispatcher that does not stamp, every call is **no context** (refused).

### 6.3 Gate (`vx_write_gate.py`), run first in `remove_document`, `delete`, `upsert`. **Fails closed.**

| Condition (checked in order) | Result |
|---|---|
| any id is `schema` — in the three tools **and in `StoreInstanceBase.writeDocuments` (`sib:65-75`) for the data lane**; `addChunks(checkCollection=False)` (the control-record path, `ds:535`) is exempt | `RESERVED_ID` (data lane: the pipe fails with "reserved objectId") |
| `current_tool_call()` is `None` | `WRITES_UNKNOWN_CALLER` |
| `origin == 'agent'` and `agent_writes` true | allowed (logged) |
| `origin == 'agent'` and `agent_writes` false | `WRITES_AGENT` |
| `origin == 'dap'` and `allow_writes` false | `WRITES_DISABLED` |
| `source_type != 'tools'` (including `None`) | `WRITES_SOURCE` |
| `caller.auth` not in `('account','task')` | `WRITES_PUBLIC` |
| `targeted` false | `WRITES_BROADCAST` |
| external `upsert` with `embedding` | `INVALID_INPUT` |
| otherwise | allowed, audited |

Refusals return the envelope and never raise; the tools stay listed for DAP.

### 6.4 Audit
- Write tools return the `audit` block. `cmd_data` forwards a result carrying `audit` to `account.audit(user_id, source='vector', reason=audit.action, request_data={node, provider, collection, object_ids, caller.auth, teamId, source}, response_data={rows, success|code}, org_id)` (`base.py:292-315`). The node logs one line per write with ids and counts only.
- Only an action in the store tools' namespace is recorded: `audit.action` must fully match `vector\.[a-z][a-z0-9_]{0,63}` (`vector.remove_document`, `vector.delete`, `vector.upsert`; `AUDIT_ACTION_PATTERN` in `cmd_data`). A result whose `audit` block names anything else is answered as usual and not recorded. At most 100 object ids go into one record.
- Uploads are not audited separately: they travel the ingest source's data lane like any other upload.

### 6.5 Gate tests (`nodes/test/test_vector_write_gate.py`; mirrored live by the tool-path suite)
- No context → `WRITES_UNKNOWN_CALLER`, data unchanged. Agent context, defaults → allowed; `agent_writes=false` → `WRITES_AGENT`. DAP context: every row of §6.3 in order. `source_type=None` → `WRITES_SOURCE`. Simulated `ImportError` → refused. A param whose `input` contains a forged `__tool_context__` → ignored. Client-sent `caller` overwritten. Audit block carries no content keys. The expectation table imports `VECTOR_ALLOW_WRITES_DEFAULT`.
- `createCollection` on an empty mocked driver succeeds; `writeDocuments` with objectId `schema` fails before `addChunks`.
