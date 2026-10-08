---
title: Vector Explorer
---

# Vector Explorer

Vector Explorer is the app for managing the documents in a vector store your
pipelines already use. Its main screen is a console: how many documents and
chunks the store holds, a directory of every document with a button to remove
it, a drop zone that adds files, and a chat that answers from those documents.
A second tab, the map, shows how close the chunks are to each other and to a
question you type.

It is not a database client of its own. Every request goes through a store node
inside one of your running pipelines, so it reaches exactly the collection that
node is configured for, with that node's settings. If apps are new to you, read
[Apps](/concepts/apps) first. What the app deliberately does not do is under
[Limits](#limits).

Four stores are supported:
[PostgreSQL with pgvector](/nodes/store_postgres),
[RocketRide Vector](/nodes/rocketride_vector) (your organization's managed
RocketRide database), [Qdrant](/nodes/store_qdrant) and
[Chroma](/nodes/store_chroma). [Milvus](/nodes/store_milvus),
[Weaviate](/nodes/store_weaviate), [Pinecone](/nodes/store_pinecone),
[Astra DB](/nodes/store_astra) and [MongoDB Atlas](/nodes/store_atlas) are
available but marked **Experimental**: a store is marked supported only after
its tests against a live server pass, and in this build these five were tested
against mock clients only. The level each connection shows is the one its node
reports.
[Elasticsearch and OpenSearch](/nodes/store_elasticsearch) are not supported and
are never listed.

## Before you start

- **A pipeline laid out for Vector Explorer.** Nine starting pipelines, one
  per store (`postgres.pipe`, `rocketride_vector.pipe`, `qdrant.pipe`,
  `chroma.pipe`, `milvus.pipe`, `weaviate.pipe`, `pinecone.pipe`, `astra.pipe`,
  `atlas.pipe`), are kept in the RocketRide repository under
  [`apps/vector-ui/templates`](https://github.com/rocketride-org/rocketride-server/tree/develop/apps/vector-ui/templates).
  They are not installed with the app, and none holds a password, a real key
  or a `project_id`. Each has three sources:
  - **Ingest** ([Drag & Drop](/nodes/webhook/dropper)): files sent here are
    parsed, chunked, embedded and written to the store. The app's drop zone
    uses it.
  - **Chat** ([Chat](/nodes/webhook/chat)): questions are embedded, matched
    against the store, and answered by an LLM, which also returns the chunks it
    was given.
  - **Tools** ([Tools](/nodes/webhook/tools)): the app's own requests (counts,
    the directory, removal, the map).

  The pipeline has two store nodes on the same collection. `store_1` is the one
  Vector Explorer manages; `store_2` answers the chat. Give both the same
  connection settings and collection.
- **Saved as a project, so its sources are grouped.** The three sources are
  separate tasks, and the app groups them into one connection by the
  pipeline's `project_id`. Open a template, save its text as a new `.pipe` file
  in a VS Code workspace, and the editor gives it its own `project_id`, so two
  people importing the same template never share an identity. A pipeline
  started without one shows each source as its own card, and the drawer says
  "Other sources not found: save the pipeline with a project id so its sources
  are grouped."
- **All three sources running.** Start each source of the pipeline. From an
  SDK that is one `use()` per source; give the pipeline a `project_id` once and
  keep it, pass `ttl=0` if the pipeline should not stop after 15 idle minutes,
  and pass `use_existing=True` (TypeScript `useExisting: true`) so that starting
  a source that is already running hands back the running task instead of
  failing with "Pipeline is already running.":

  ```python
  import json

  pipeline = json.load(open('postgres.pipe'))
  pipeline['project_id'] = '…'   # one fixed id for this pipeline, e.g. a uuid4 you keep
  # client: a connected RocketRideClient
  for source in ('ingest_1', 'chat_1', 'tools_1'):
      result = await client.use(pipeline=pipeline, source=source, ttl=0, use_existing=True)
  ```

  `result['reused']` is `True` when the source was already running.
- **Your store's connection details.** Type them into the store nodes' forms.
  The app never shows them, and store nodes never return them. A `.pipe` file
  is plain JSON and keeps what you type as written, so treat it like any file
  that holds a password. `rocketride_vector` has none to type: it uses your
  organization's managed RocketRide database.
- **A key for the chat's LLM.** The templates ship with the placeholder key
  `replace-with-your-key` and an empty `base_url` on the LLM node
  ([OpenAI-Compatible API](/nodes/llm_openai_api)). Replace the key, and set
  `base_url` only for an OpenAI-compatible server other than OpenAI. Until you
  do, the chat source cannot answer: an empty `base_url` sends questions to
  OpenAI, which refuses the placeholder key (or, offline, cannot be reached).
  Everything else (counts, the directory, adding and removing documents, the
  map) works without an LLM.
- **Removing documents needs the write switch.** Each store node has an
  **Allow document management from tool calls** setting (`allow_writes`). It
  is off by default on every store node. The Vector Explorer templates turn it
  on for `store_1` and leave it off for `store_2`. To turn it on in a pipeline
  of your own, switch it on in the store node's settings, or set
  `config.<profile>.allow_writes` to `true` on the store component in the
  `.pipe` (for example `"local": { …, "allow_writes": true }`), then restart the
  pipeline. With it off, the trash buttons are disabled and say why. Adding
  documents is not governed by this switch: it goes through the Ingest source,
  and anyone with the data permission on the ingest task can add documents.
  Agents that use a store as a tool are unaffected; they have their own switch,
  `agent_writes`, which is on by default.
- **No Tools source? The card is read-only.** A pipeline with a vector store
  but no running Tools source, such as an ordinary RAG chat pipeline, is still
  listed, marked **Read-only** and reached through its Chat (or else Ingest)
  source. Counts, documents, chat and the map work where the store answers
  them; adding and removing documents are disabled with the reason "No Tools
  source: documents cannot be added or removed from here".
- **Trying it without a model.** The repository's acceptance scripts include a
  local stub of an OpenAI-compatible server,
  [`stub_llm.py`](https://github.com/rocketride-org/rocketride-server/blob/develop/scripts/acceptance/vector-explorer/stub_llm.py).
  It is a test stand-in, not a model: its answers start with `[STUB-LLM]` and
  prove only that retrieval reached the LLM node. The test fixtures rename the
  LLM node to "Local stub LLM" so the chat header says what it is. The stub
  logs every request, which includes document text, to its own `out/` folder.
- **Know what leaves the store.** Read [Privacy](#privacy) before adding
  anything sensitive, and [Where document paths come from](#where-document-paths-come-from)
  before trusting a path.

## Connections

The Connections page lists one card per store node that a running pipeline's
Tools source controls, so `store_2` never appears, and one read-only card per
store node of a running pipeline that has no Tools source. SQL and graph nodes
are never listed. A card shows:

- the store node's name, then `<store> · <collection> · <pipeline>`;
- the roles: `ingest ✓ · chat ✓ · tools ✓`, with `–` for a source that is not
  running;
- a state: **Checking**, **Running**, **Stopped**, **Unreachable** or
  **No access**;
- notes when they apply: **Experimental**, **Read-only**, **Empty collection**
  (the collection does not exist yet; the first upload creates it), **Repair
  needed** (the collection's control record, which the store node writes when
  it creates the collection, is missing), and **Metadata column pending**
  (pgvector: file size and ingest time are not stored yet, see
  [What the notes mean](#what-the-notes-mean)).

A store node the anchor source cannot reach is shown Stopped with "Not
reachable from the Chat source" (or Ingest). When nothing is listed, the page
says "No running pipeline has a vector store. Start one of the Vector Explorer
templates (`templates/<store>.pipe`) and save it as a project, then refresh."

Selecting a card opens a drawer with the roles, the backend and its version,
the collection, metric, embedding model and dimension, the index, the embedding
and LLM node names, whether removing documents is on, the support level and a
sentence per note. For `rocketride_vector` it adds: "Shared table: every
pipeline in this organization that names table '`<table>`' reads and writes these
rows." From a pipeline's configuration the app shows only the provider, the
node name, the pipeline name and the collection.

## The console

Opening a connection shows its console: the stats strip across the top, the
document directory on the left, and on the right the drop zone above the chat.
Below 900 pixels wide the panels stack.

### Stats

Documents, chunks, deleted chunks, average chunks per document, the embedding
model and dimension, the metric and the index type. They are counted when the
console opens, after every removal or completed upload, and on **Refresh**.
While the console is visible a lighter check runs at most every 15 seconds and
the strip says "counts as of N s ago". Numbers the node did not return are
shown as "—" with a tooltip, never estimated: Pinecone, for example, cannot
count. "N without first chunk" means N documents have lost their first chunk
(left by an older node or an interrupted ingest); they are still documents and
are listed in their own group.

### Documents

Every document is listed once, by its path, with its chunk count, folders built
from `/` and `\` (Windows drive roots included). Names without a folder are
grouped under **Uploaded**, and documents without a first chunk under
**Without first chunk**. Two documents with the same path are both listed;
hover shows their short ids.

The first page loads at once, then the rest load in the background, up to
5,000 documents, with "Loading documents… 1,200 of 10,000". The list does not
reshuffle while pages arrive; it is re-sorted when loading finishes. Past
5,000, or when a store cannot page its list, the footer reads "Limit reached at
N documents; more may exist" with **Load more**. The filter box works on the
documents loaded so far and says so while loading continues.

Selecting a document lists its chunks, 100 at a time, each with its length and
a **map** button.

### Adding documents

Drop files or folders on the drop zone, or use **Add files** and **Add
folder**. A folder keeps its structure in the stored paths, and the **Store
under folder** box puts a prefix in front of every path. Accepted: PDF, DOCX,
PPTX, XLSX, ODT, RTF, TXT, MD, CSV, HTML and JSON, up to 20 files per drop,
50 MB per file and 200 MB per drop. A drop with the same path twice is refused
before anything is sent.

Before sending, the app checks each path against the store. If a document with
that path exists, it asks "Replace existing '`<name>`' (N chunks)? The old chunks
are removed when the new file is stored." with **Cancel** focused. Each file
then shows queued, uploading, processing, and "N chunks added". A failed upload
says "Failed. The engine did not return the reason; the pipeline's run log
may. The document was not added." Files with the same name in different folders
are sent one after another so each row reports its own file.

When the Ingest source feeds more than one store node, the panel names the
others: "This pipeline's ingest also reaches: `<names>`". Without a running
Ingest source, or on a read-only card, the panel says so instead.

### Chat

Ask a question about the documents (up to 4,000 characters, one at a time). The
answer comes with its **sources**: the chunks the store returned for the
question, with rank, path, chunk number and score (hover for the raw score and
how it is computed), expandable text, **open** (the document at that chunk) and
**map** (the chunk on the map). Answers are shown as plain formatted text: raw
HTML and remote images in an answer are not rendered.

**Why these?** re-runs the search with the question and shows every candidate:
the node's score threshold, the store's floor below which rows are dropped, the
near misses greyed out, and a histogram of scores. It is hidden when the
pipeline's embedding node cannot be reached from the app.

The app stops waiting after 120 seconds: "Stopped waiting after 120 s. The
pipeline may still be answering; there is no way to cancel it from here." The
chat header names the LLM node. The question history keeps your questions only.

## Removing documents

Each document has a trash button ("Remove `<path>` from the database"). It is
enabled only when the store node allows it, the connection has a Tools source,
and the card is not read-only; otherwise it is disabled and says why.

The confirmation shows the path, the short id, the chunk count and the store,
collection and backend: "Removes this document and its N chunks from
`<collection>`. This cannot be undone; add the file again to restore it."
**Cancel** has the focus, and Enter never confirms. Removing several documents
at once (select them, or lasso them on the map) asks you to type the count,
removes them in batches, and stops at the first error, saying what was removed.
On `rocketride_vector` you type the table name, because the table is shared by
every pipeline in the organization that names it.

After a removal the counts and the directory refresh and the app announces
"Removed `<path>` (N chunks)", with the number of chunks the store actually
removed. If the request times out: "The request may still complete on the
server. Refresh to check." Writes are never retried.

When the store refuses, the app says why:

| The store's answer | What the app says |
| --- | --- |
| Removal switched off | Removing documents is turned off on this store node (allow_writes). |
| Not a Tools source | Only a Tools source may remove documents. |
| The engine did not identify the caller | The engine did not identify this request, so the store refused the write. Update the engine to a version that supports the Vector Explorer. |
| The collection's control record | That record is the collection's control record and cannot be removed. |
| Anything else | The store refused this request; see the pipeline's run log. |

## The map

The **Map** tab draws a sample of the collection's chunks, each as a point,
placed so that chunks with similar meaning sit close together. It is hidden,
with the reason, when the store node cannot sample; the console is unaffected.

- **Sample.** **Detailed** draws up to 2,000 points with a short snippet each;
  **Light** draws up to 5,000 points without text (the inspector fetches it on
  demand). The label says how many of how many chunks are shown and whether the
  sample is random or not uniform, and says so when the store returned fewer
  points than asked for.
- **Layout.** The first picture is a PCA projection computed on the node.
  **Neighbour graph** refines it in your browser by pulling each chunk towards
  its nearest neighbours, and is kept only when it preserves neighbours at
  least as well as PCA; otherwise the map says "Neighbour layout did not improve
  on PCA for this sample". **t-SNE** is offered up to 1,000 points. Both have a
  time limit and **Cancel**. The legend reminds you that 2D distance is
  approximate; ranks and scores are exact. On Qdrant the neighbour graph is
  computed by Qdrant, and the legend says "neighbour graph computed by Qdrant".
- **Query.** Type text and **Run**: the text is embedded by the pipeline's
  embedding node, drawn as a star, and joined by rays to its true top results
  from the whole collection, not only from the sample. This needs the embedding
  node to be reachable from the Tools source; otherwise it is disabled with the
  reason.
- **Point.** Hover shows the document and snippet. Click lists the 12 nearest
  chunks in the whole collection with their similarity; neighbours outside the
  sample are drawn hollow. **Open document**, **Find similar** and **Remove
  document** act on it.
- **Answers.** The sources of a chat answer light up on the map; sources
  outside the sample are added to it.
- **Lasso** (`L`): select an area, then **Ask about these only**, **Remove
  these documents** or **Copy keys**.
- **Duplicates, Outliers, Heat strip and Table.** Near-identical chunks are
  joined by a dashed line, unusually isolated chunks are ringed, the heat strip
  shows a document's chunks in order against the active query, and the
  **Table** tab lists the points for screen readers and keyboard use.
- **Keyboard.** The arrow keys move to the nearest point in that direction,
  Enter inspects it, Escape clears.

The map works on positions and neighbour lists computed by the store node; the
browser never receives the raw embedding vectors of a sample.

## A document's page

**Open** on a document, a source or a point opens the document's page: its
path, id (with a copy button), chunk count, size, type and ingest time when the
store keeps them, a note when its first chunk is missing, and its chunks in
reading order with table chunks tagged. **Show chunk path on map** draws the
document's chunks in order on the map.

## What the notes mean

**Experimental** is the support level the store node reports, not a note with
a sentence of its own: a store is marked supported only after its tests
against a live server pass. The other notes are explained by these sentences:

| When | The app says |
| --- | --- |
| The store searches exactly, without an index | This store searches by brute force (exact); large collections answer slowly. |
| The store's scores are not on a 0–1 scale | Scores are the backend's raw values, not 0–1. |
| The store does not keep the extra file details | This backend does not keep file size or ingest time. |
| The store is a cloud service that was not checked against a live server | This backend was not run against a live server in this build. |
| The store counts documents by their first chunk | Documents are counted by their first chunk on this store. |
| More than 1,000 documents lack a first chunk | Orphan counts above 1,000 are not exact on this store. |
| The store lists documents unsorted | This store lists documents in storage order; the directory sorts what is loaded. |
| The store cannot page its document list | This store cannot page its document list; only the first page is shown. |
| The chat's embedding model is not the collection's | The chat embedding model differs from the one this collection was built with; results may be meaningless. |
| pgvector could not add its metadata column yet | File size and ingest time are not stored yet: another session holds this table; the store will retry. |

## Where document paths come from

The path a document shows is a label the store keeps with every chunk, written
by whatever added the document:

- **Added here**, it is the path of the file relative to what you dropped: a
  file's own name, or `folder/sub/file.pdf` for a folder, with the **Store
  under folder** prefix in front when you set one. Browsers do not tell a web
  page where a file sits on your disk, so a full path such as `C:/…` appears
  only if you typed it as the prefix. Paths are cleaned before sending: Unicode
  normalised, control and bidirectional characters removed, `..` and a leading
  `/` refused, each folder or file name at most 255 bytes. A file without a
  folder is listed under **Uploaded**.
- **Added by another pipeline**, it is whatever that pipeline's source
  recorded, for example a file-system path or an object-store key.

A path is not a location: the app never opens a file at that path, and the path
does not prove where the file is now or who added it. The same path does mean
the same document, though: the document's id is derived from its path, so
adding a file under a path that is already stored replaces that document, which
is why the app asks first. Uploads from the app are tagged as coming from
Vector Explorer, and a line is logged when one is stored.

## Privacy

- **Only through your nodes.** The app sees what the pipeline's nodes return
  and nothing else. Store nodes never return a host, connection string,
  credential or database name.
- **Tokens stay in memory.** The tokens of the pipelines' tasks are kept in
  memory for the session only, never in history, preferences or anything saved.
  When you sign out, or switch organization or team, every connection, list,
  chat, map and selection is cleared.
- **Run log traces.** When a pipeline runs with tracing on (the `summary` or
  `full` trace level; the VS Code extension starts runs with `full`, an SDK
  `use()` with `none`), its run log records each tool call's input and the
  first 2 KB of its output. For Vector Explorer that means your map queries,
  document paths and ids, snippets of chunk text, and for a `vectors` answer
  (the one request that returns raw embedding values) the start of the raw
  vector. The chat's questions and the chunks passed to the LLM travel through
  the pipeline's lanes and are recorded at those levels too. Run logs are kept
  7 days for development runs and 30 days for deployments; see
  [Observability](/guides/observability). If that matters, start the pipeline
  with tracing off.
- **Chat history** keeps the text of your questions only, and is forgotten on
  sign-out.

## Limits

- **Removal cannot be undone.** There is no trash to restore from; add the file
  again.
- **No cancel on the server.** A question, an upload or a sample already
  running on the server cannot be cancelled from the app; it only stops
  waiting. A removal that timed out may still complete. (A layout runs in your
  browser and has **Cancel**.)
- **Elasticsearch and OpenSearch** store nodes are not supported and are not
  listed.
- **Experimental stores** (Milvus, Weaviate, Pinecone, Astra DB, MongoDB Atlas)
  were tested against mock clients only in this build. Pinecone cannot count
  documents or chunks and has no keyword search.
- **Size.** The map draws at most 2,000 points in detailed mode and 5,000 in
  light mode, and t-SNE at most 1,000. The directory loads 5,000 documents on
  its own; **Load more** goes further.
- **Uploads.** 20 files, 50 MB per file and 200 MB per drop, checked by the
  app; the templates also set the parser's file-size limit to 50 MB. The engine
  itself does not limit how much an upload writes.
- **Read-only cards** cannot add or remove documents.
- **Answers need a model.** Chat needs a working LLM (a key, or a local
  OpenAI-compatible server); everything else does not.

## Compared with the native consoles

Vector Explorer does not replace your database's own console. Where it goes
further:

- a text query placed on the map, with rays to its true top results from the
  whole collection;
- chat answers linked to the exact chunks they were given;
- document-level removal that reports the rows actually removed;
- one interface across four backends: pgvector, RocketRide Vector, Qdrant and
  Chroma;
- duplicates and outliers found on the store node.

The map draws up to 2,000 points in detailed mode and 5,000 in light mode;
Qdrant's own visualiser draws more. On Qdrant, Vector Explorer asks Qdrant for
the neighbour graph rather than computing it.
