# rocketride_vector

A RocketRide vector store node that stores embedded document chunks and retrieves
them by keyword or semantic similarity from your organization's managed
RocketRide database. Pick it over the SQL and graph nodes for retrieval-augmented
document search.

## What it does

The node writes documents from the documents lane into a pgvector-backed table.
A batch that carries a document's first chunk replaces every chunk stored for
that document; a later batch of the same document adds its chunks, so a long
document that the embedding node sends in several batches is stored whole.
Questions can produce matching documents, answers, or enriched questions through
the three configured question outputs. The node is also a tool: an agent can
search the table and manage its documents, and the Vector Explorer app browses,
maps and edits it through a Tools source.

It stores through the same pgvector driver as the PostgreSQL store
(`store_postgres`); the two differ only in how they reach the database and in
their configuration.

## Lanes

| Lane in | Lane out | Description |
| --- | --- | --- |
| documents | — | Stores document chunks in the configured vector table. |
| questions | documents | Returns matching documents. |
| questions | answers | Returns matching documents as answers. |
| questions | questions | Enriches a question with matching documents. |

## As a tool

The tool-server name is `rocketride_vector`.

| Function | Description |
| --- | --- |
| `search` | Searches the table for a non-empty `query`; accepts an optional `top_k` and a metadata `filter`, and returns matching content, metadata and scores. Needs an embedding provider bound to the node. |
| `upsert` | Adds or replaces documents from a non-empty `documents` array; each needs `content` and an `object_id`. |
| `delete` | Removes every chunk of the documents in a non-empty `object_ids` array. |
| `objdir` | Lists the stored document paths, optionally under a `parent` path, with `offset` and `limit`. |
| `get` | Returns the chunks of one `object_id` in chunk order, with `offset` and `limit`. |
| `stats` | Reports the number of stored rows, the embedding model and the vector size. |

`upsert` and `delete` change the table. When an agent in the pipeline calls
them, Allow agent writes decides; when a Tools source calls them (an SDK script,
or the Vector Explorer), Allow document management from tool calls decides, and
it is off by default. The collection's control record (object ID `schema`) can
never be removed or overwritten through a tool.

## Configuration

The single cloud profile provides a table, cosine similarity, a score threshold,
and HNSW index defaults. RocketRide provisions one database per organization for
its managed database nodes (per user only where there is no organization), and
the RocketRide server resolves the connection to it from the pipeline's
organization instead of a host, user, password, or database name you enter;
nothing in the node configuration or the pipeline can point it at another
database. Bind an embedding module for semantic search; the embedding dimension
is taken from the first stored document rather than from a configuration field.

### Table

Table defaults to rocketride and is the PostgreSQL table that holds the chunks
and embeddings. Choose a distinct table when separate corpora need separate
retrieval indexes or retention behavior. The node accepts only an unquoted
PostgreSQL identifier: it must start with a letter or underscore, use only
letters, digits, and underscores, and be at most 63 characters. Invalid names
are rejected during configuration validation and at startup. The name is used
in lower case, as PostgreSQL itself would read it (`MyDocs` is the table
`mydocs`).

The table is shared by every pipeline of the organization that names it: they
all read and write the same rows.

### Score threshold and similarity metric

Score threshold defaults to 0.5; it is the minimum returned similarity score.
Raise it when loose matches are polluting downstream context, and lower it when
relevant documents are being excluded. Scores are calculated from the
configured metric: cosine uses 1 - distance, L2 uses 1 / (1 + distance), and
inner product negates the returned distance. Regardless of this setting, the
store drops results below its fixed 0.20 minimum similarity floor.

Similarity Metric defaults to cosine; l2 and inner_product are also accepted.
Select the metric that matches the embeddings and expected notion of closeness
before the table is first written, because it chooses the HNSW operator class
used for the index. An unsupported value prevents startup.

### HNSW m and ef_construction

The table's HNSW index is created on first write. HNSW m defaults to 16 and
controls the graph degree; HNSW ef_construction defaults to 64 and controls the
candidate list used while building it. Higher values can improve search quality
at the cost of a more expensive, larger index. Values are clamped to pgvector's
supported ranges (m 2–100 and ef_construction 4–1,000), and ef_construction is
raised to at least twice m. These values do not rebuild an index that already
exists.

### Write switches

Allow document management from tool calls (`allow_writes`) is off by default.
Turn it on in the pipeline whose Tools source should be able to remove documents
from the table, for example the pipeline the Vector Explorer manages. Even when
it is on, a removal is accepted only from a Tools source of the pipeline,
addressed to this node; calls from the pipeline's chat or ingest sources are
refused. Because the table is shared by the organization's pipelines, removing a
document removes it for all of them.

Allow agent writes (`agent_writes`) is on by default and keeps an agent's
`upsert` and `delete` calls working as before. Turn it off when the agents of
this pipeline should only search.

## Notes

### Storage and retrieval behavior

The node creates the table on the first write, with an index on object ID and
chunk ID and, up to 2,000 dimensions, a metric-compatible HNSW index. pgvector
cannot create the HNSW index for wider embeddings, so the node warns and
searches without it in that case. Metadata the table has no column for, such as
a file's size or ingest time, is kept in a `meta` JSON column. A table written by
an earlier version of the node gets that column when the node starts; if
another session holds the table at that moment, the node writes without it for
now (the extra metadata is not stored) and tries again at most once a minute.

Keyword search is a case-insensitive substring match on the question text.
Semantic search needs an embedding bound to the question and raises if none is
available; filtered searches keep scanning the HNSW index until they have enough
rows. Missing tables produce empty search results rather than an error. Deleted
objects are excluded by default, while document rendering reassembles stored
chunks in chunkId order.

### Connections

The node opens at most four connections to the database, only when it needs
them, and closes a connection that stayed idle for a minute. Every call runs in
one short transaction that always ends: reads are read-only and limited to 30
seconds per statement, and a batch of writes is applied together or not at all,
one batch at a time across every pipeline writing the table. Nothing is set for
the database session, so the node works through a transaction-mode connection
pooler. Errors never name the database server, user or database.

<!-- ROCKETRIDE:GENERATED:PARAMS START -->
<!-- Generated by nodes:docs-generate. Do not edit by hand. -->

## Schema

| Field | Type | Description | Default |
|---|---|---|---|
| `rrvector.collection` | `string` | **Table**<br/>Name of the table to store vectors in your RocketRide cloud database. | `"rocketride"` |
| `rrvector.hnsw_ef_construction` | `integer` | **HNSW ef_construction**<br/>HNSW build-time candidate list size used when the index is first created. | `64` |
| `rrvector.hnsw_m` | `integer` | **HNSW m**<br/>HNSW graph degree (max connections per layer) used when the index is first created. | `16` |
| `rrvector.profile` | `string` | **RocketRide cloud database**<br/>Connect to... | `"cloud"` |
| `rrvector.provider` | `string` |  | const: `"rocketride_vector"` |
| `rrvector.score` | `number` | **Score threshold**<br/>Minimum similarity score for a document to be returned by search. | `0.5` |
| `rrvector.similarity` | `string` | **Similarity Metric**<br/>The similarity metric to use for vector search. Also selects the HNSW index operator class. | `"cosine"` |

## Dependencies

- `psycopg2-binary`
- `pgvector`

## Source

[<svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor" aria-hidden="true" style="vertical-align:-0.15em;margin-right:0.35em"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg> View source](https://github.com/rocketride-org/rocketride-server/tree/develop/nodes/src/nodes/rocketride_vector)
<!-- ROCKETRIDE:GENERATED:PARAMS END -->
