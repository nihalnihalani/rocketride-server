# Vector Explorer

Vector Explorer is the console for a vector store your pipelines already
write to: see how many documents and chunks it holds, list every document by
its path, remove a document, drop new files in to add them, ask questions over
what is stored, and map the chunks to see which ones sit close together. It is
not a database client of its own. Every call travels through a store node
inside one of your running pipelines, so it reaches exactly the collection that
node is configured for, with that node's settings. If apps are new to you, read
[Apps](https://github.com/rocketride-org/rocketride-server/blob/develop/docs/public/product/concepts/apps.md)
first. What the app deliberately does not do is under [Limits](#limits). The
full user guide, from preparing a pipeline to what every note means, is
[Vector Explorer](https://docs.rocketride.org/guides/apps/vector-explorer) on
docs.rocketride.org.

The store nodes it opens are
[`postgres`](https://github.com/rocketride-org/rocketride-server/blob/develop/nodes/src/nodes/store_postgres/README.md)
(pgvector),
[`rocketride_vector`](https://github.com/rocketride-org/rocketride-server/blob/develop/nodes/src/nodes/rocketride_vector/README.md)
(your organization's managed RocketRide database),
[`qdrant`](https://github.com/rocketride-org/rocketride-server/blob/develop/nodes/src/nodes/store_qdrant/README.md)
and
[`chroma`](https://github.com/rocketride-org/rocketride-server/blob/develop/nodes/src/nodes/store_chroma/README.md),
plus Milvus, Weaviate, Pinecone, Astra DB and MongoDB Atlas, which are marked
**Experimental**: their drivers were not run against a live server in this
build. Elasticsearch and OpenSearch store nodes are not listed: they do not
answer the Vector Explorer tools.

## Before you start

- **A pipeline laid out for Vector Explorer.** Nine starting pipelines, one per
  store (`postgres.pipe`, `rocketride_vector.pipe`, `qdrant.pipe`,
  `chroma.pipe`, and the experimental `milvus.pipe`, `weaviate.pipe`,
  `pinecone.pipe`, `astra.pipe` and `atlas.pipe`), are kept in the RocketRide
  repository under
  [`apps/vector-ui/templates`](https://github.com/rocketride-org/rocketride-server/tree/develop/apps/vector-ui/templates).
  They are not installed with the app. Each has three sources: **Ingest** (a
  dropper the app sends files to), **Chat** (questions) and **Tools** (the app's
  own calls), a parser, a chunker, an embedding node, two instances of the same
  store on the same collection (`store_1`, which the app manages, and
  `store_2`, which the chat reads), an LLM node and the two response nodes. They
  hold no password, token or `project_id`. To use one, open it there and save
  its text as a new `.pipe` file in a VS Code workspace: the editor gives a new
  `.pipe` file its own `project_id`, and the app groups a pipeline's three
  sources by it. Type the store's connection details into its form. Both store
  nodes keep chunks with a cosine similarity of at least 0.3 to the question,
  written on the store's own score scale: `0.3` on pgvector, RocketRide Vector
  and Pinecone, `0.65` (that is, (1 + 0.3) / 2) on the other stores.
- **All three sources running.** Connections are discovered from running tasks.
  A pipeline whose Tools source is not running still appears, as a
  **Read-only** card (see [Connections](#connections)).
- **An LLM key, only for the chat.** The templates' LLM node carries the
  placeholder `replace-with-your-key`; replace it with your key, and set
  `base_url` only for an OpenAI-compatible server other than OpenAI. Until
  then the chat cannot answer; everything else works.
- **Removing documents is a node setting.** Each store node has **Allow
  document management from tool calls** (`allow_writes`). It is off unless the
  pipeline turns it on; the templates turn it on for `store_1` only. With it
  off, the trash buttons are disabled and say why.

## Connections

The Connections page lists one card per store node a running Tools source
controls. A card shows the node's name, the store, the collection and the
pipeline, which of the pipeline's three sources are running
(`ingest ✓ · chat ✓ · tools ✓`), and a state: **Checking**, **Running**,
**Stopped**, **Unreachable** or **No access**. Further badges say
**Experimental**, **Empty collection** (the collection does not exist yet; add a
document to create it), **Repair needed** (the collection's control record is
missing) and **Metadata column pending** (pgvector: another session holds the
table, so file size and ingest time are not stored yet; the node retries).

`store_2`, the chat path's copy of the store, is never a card. SQL and graph
nodes are never cards.

A pipeline with vector stores but no running Tools source (for example the
stock RAG template, a webhook and a chat) is listed as a **Read-only** card,
anchored on its Chat source (or its Ingest source when chat is not running):
documents cannot be added or removed from there, and the card says so. A store
the anchor source cannot reach is shown **Stopped**, "Not reachable from the
chat source".

The drawer of a card shows the roles, the backend and its version, the
collection, metric, embedding model and dimension, the index, the embedding and
LLM node names, whether removing documents is on, the support level and any
caveat. For `rocketride_vector` it adds: "Shared table: every pipeline in this
organization that names table '<table>' reads and writes these rows." It never
shows a host, a connection string, a credential or a database name.

Signing out, or a switch to another organization or development team, forgets
every connection, closes every console and document tab, and clears every
cache (documents, chunks, uploads, chat, samples and the selection).

## The console

Opening a connection opens its console, the main screen.

- **Statistics** across the top: documents, chunks, deleted chunks, average
  chunks per document, the embedding model and dimension, the metric and the
  index. The figures come from the node's `stats` tool: a full count when the
  console opens, after a removal or a completed upload and on **Refresh**, and
  a quick refresh at most every 15 seconds while the console is visible, which
  says "counts as of 12 s ago". A figure the store cannot count shows "—" with
  a tooltip saying so (Pinecone counts nothing per document). Chips name what
  qualifies the figures: **Experimental**, **Brute-force search**, **Writes
  on/off**, **Read-only**, **N without first chunk** and caveats such as
  "Scores are the backend's raw values, not 0–1."
- **Documents** on the left: every document once, by its path, grouped into
  folders by `/` and `\` (Windows drive letters and network shares are kept as
  roots; a bare file name goes under **Uploaded**; a document whose first chunk
  is missing goes under **Without first chunk**). The list loads its first page
  at once and keeps loading in the background up to 5,000 documents ("Loading
  documents… 1,200 of 10,000"); rows are re-sorted only when loading ends or
  pauses, so nothing moves under the pointer. Past 5,000 the footer says "Limit
  reached at 5,000 documents; more may exist" with **Load more**. A store that
  lists documents in storage order is sorted here, and the footer says so; when
  a store sends back documents already listed instead of the next page, loading
  stops there and the footer says that too. The filter box filters what is
  loaded. Selecting a document lists its chunks.
- **Remove**: the trash button of a row removes that document and all its
  chunks, after a confirmation whose **Cancel** has the focus. The answer says
  how many chunks were removed, and the statistics and the list refresh. Select
  several rows to remove them together: you type the count to confirm, they go
  in batches of at most 100, and the first error stops the run and says what
  already ran. On `rocketride_vector` you type the table name instead, because
  the table is shared by every pipeline of your organization that names it.
- **Add documents** at the top right: drop files or folders, or use **Add
  files** / **Add folder**. Each upload shows its progress and then "N chunks
  added".
- **Chat** at the bottom right: ask a question over the stored documents; the
  answer lists the chunks it was given, each with **open** (the document, at
  that chunk) and **map**.

A document tab shows one document: its path, objectId, chunk count, size,
type and ingest time where the store keeps them, and every chunk in reading
order.

## The map

The **Map** tab of a connection draws a sample of the chunks (up to 2,000 with
text, or 5,000 points without) positioned by their embeddings, so chunks that
say similar things sit close together. A text query is placed on the map with
rays to its true top matches; a point shows its 12 nearest chunks in the whole
collection; duplicates and outliers are listed; every action leads back to the
console. **Table** lists the same points for keyboard and screen-reader use.

## Adding documents

- Up to 20 files per drop, 50 MB per file and 200 MB per drop; PDF, DOCX, PPTX,
  XLSX, ODT, RTF, TXT, MD, CSV, HTML and JSON. The app checks these limits
  before sending: a file over a limit is excluded, not ingested, and its row
  says why ("Not added: larger than 50 MB."). The engine does not apply the
  templates' parser cap (`parse_1.config.index.maxFileSize`) in this release,
  so the app's limits are the only ones.
- A file is stored under its path in the drop (a folder keeps its structure);
  **Store under folder** puts a prefix in front. Dropping a file whose path is
  already stored asks before replacing it; the old chunks are removed when the
  new file is stored.
- An upload that completes but leaves no chunks in the store (for example a PDF
  without text the parser can read) says "Not added: the pipeline stored no
  chunks for this file." once the store still does not list it a few seconds
  later.
- Anyone with the data permission on the Ingest task can add documents, with or
  without this app.

## Privacy

- The app never saves a task token, a connection string or a document's
  content. Chat history keeps your questions only, and is cleared with the
  connections.
- When a pipeline run is traced, the run log keeps each tool call's input and
  the first 2 KB of its output. That includes chunk text the console listed and,
  for the one tool that returns stored vectors (`vectors`, at most two at a
  time), the first values of those vectors.

## What it does that the stores' own consoles do not

Within one app, across pgvector, RocketRide Vector, Qdrant and Chroma: a text
question placed on the map with rays to the chunks the store really ranks
first; chat answers linked to the chunks they used; removing a whole document
with the number of rows removed reported; near-duplicate and outlier chunks
listed; and the same console for every store. The map draws at most 2,000
points with text, or 5,000 without; Qdrant's own visualiser draws more points.
On Qdrant the neighbour graph of the map is computed by Qdrant itself.

## Limits

- **Read-only cards cannot add or remove documents.** Start the pipeline's
  Tools source to manage it.
- **Removing is per document, and cannot be undone.** Add the file again to
  restore it.
- **Counts are what the store returns.** A store that cannot count shows "—";
  the app never estimates a count.
- **No cancel.** A request the app stops waiting for may still finish on the
  server; refresh to check.
- **Elasticsearch and OpenSearch** are not supported.
- **Experimental stores** (Milvus, Weaviate, Pinecone, Astra DB, MongoDB Atlas)
  were checked against stand-ins only.
