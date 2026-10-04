# Graph Explorer

Graph Explorer is the app for working with a graph database your pipelines
already talk to: browse what is in it, run Cypher, see the answer as a graph,
and, only where a node allows it, change data. It is not a database client of
its own. Every statement travels through a graph tool node inside one of your
running pipelines, so it reaches exactly the graph that node is configured for,
with that node's permissions. If apps are new to you, read
[Apps](../../docs/public/product/concepts/apps.md) first. What the app
deliberately does not do is under [Limits](#limits).

The supported nodes are [`rocketride_graph`](../../nodes/src/nodes/rocketride_graph/README.md)
(Apache AGE), [`graph_neo4j`](../../nodes/src/nodes/graph_neo4j/README.md) and
[`graph_falkordb`](../../nodes/src/nodes/graph_falkordb/README.md). Other nodes
that declare the `graph` class, such as ArangoDB and HydraDB, do not speak
Cypher and are not listed.

## Before you start

- **A running pipeline with a graph node.** Connections are discovered from
  running tasks, so a stopped pipeline has none. Three starting pipelines ship
  with the app in [`templates/`](templates): `age.pipe`, `neo4j.pipe` and
  `falkordb.pipe`. Each is a tools source plus one graph node and a note, with
  direct execution off, and holds no password, token or `project_id`. Copy one into
  a VS Code workspace: the editor gives a new `.pipe` file its own `project_id` when
  it has none, so two people importing the same template never share an identity.
  Type the connection details into the node's form (they are stored encrypted).
  Posting the raw file through an SDK `use()` also works, but the engine then does
  not report a project id for the task, and two such runs of the same node cannot be
  told apart in the Connections list.
- **A node that is up to date.** The app reads through the node's `read_query`
  tool and reads its identity, limits and capabilities from `dialect`. A node
  that does not advertise `read_query` is shown as **Needs upgrade** and cannot
  be opened. The app never falls back to `execute`, or to FalkorDB's writable
  `query`, to read: a fallback to a tool that can write would turn a read
  screen into a write path.
- **Direct execution, only if you want to change data.** Each node has an
  **Allow direct query execution** setting (`allow_execute`), off by default and
  worth leaving off. With it off there is no write console for that connection.
- **A language model, only if you want to ask in words.** Browsing with Cypher
  needs none.

## Connections

The Connections page lists every graph node in every running pipeline task you
can see. A card shows the pipeline, the node and a state: **Running** once the
node answered, **Stopped**, **Unreachable**, **No access** (you can see a team
deployment but your role cannot call it), or **Needs upgrade**. Your own
development run and a team's deployment of the same pipeline are separate
connections, and two owners' runs never merge. Selecting a card opens a drawer
with the engine and version the node reports, its target (database or graph),
whether writes are allowed, and a sentence on what the node's read path
guarantees. **Test connection** asks the node again.

An empty list does not say why. If the task list is empty the page says that it
cannot tell whether nothing is running or something is wrong, and it claims the
graph does not exist only when a node itself said so.

The app never holds a connection string or a task token in anything it saves or
shows. Task tokens are kept in memory only, per session.

## The workbench

Opening a connection gives it a workbench: an editor, a row limit, and three
result tabs.

- **Run** sends the selection, or the statement the caret is in
  (Ctrl/Cmd+Enter). **Run all** sends every statement in order
  (Ctrl/Cmd+Shift+Enter). The text under the editor says what a press would
  send before you press it. What is sent is read from the editor at the moment
  you press, never from an earlier copy of the text.
- **Several statements** run one after another, each as its own request, and the
  run stops at the first error. A strip lists each statement with its outcome.
  Nothing here is a transaction: statements that ran before a failure have
  already run, and the page says so.
- **Row limit** is 200, 1,000 or All. All means the node's own maximum, never
  unlimited, and nothing above that maximum is ever sent. The limit travels as an
  input to the node, not as text added to your Cypher, so your statement is sent
  exactly as written.
- **Stop waiting** stops the app from waiting. The query may still be running on
  the database and cannot be cancelled from here; a late answer is ignored.
- **The editor** highlights Cypher and keeps a draft per connection (text only).
  It loads the Monaco editor from `cdn.jsdelivr.net`; where that is not
  reachable, a plain text box is used after ten seconds, with the same run keys,
  drafts and history, and a notice says so.
- **Browsing is read-only.** A statement the text check takes for a write
  (`CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`, `DROP`, `LOAD CSV`, a
  procedure that is not on the allowlist, and similar) is refused before
  anything is sent. **This is a text check, not a database safeguard.** The node
  refuses writes on its read path as well, but the real boundary is the database
  role the node connects with; see [Safety](#safety).

### Results

A result opens as a **Graph** when it holds nodes or relationships that can be
drawn, and as a **Table** otherwise. **Raw** shows the node's answer as JSON and
is always available. The Table lists every returned row positionally, so two
columns with the same name both show; selecting a row opens it in full, with
**Copy as JSON**. Integers beyond 2^53 are shown as the exact text the node sent,
never rounded, and a result that arrived with one as a plain number says that it
may have been rounded.

A result that hit a limit says which one: the row limit, the node's element
budget or its value budget.

## The graph

Nodes are coloured by their first label, with the first letter of the label
inside, and a legend lists every label next to its colour. Colour is never the
only carrier of meaning. How colours were chosen, and the contrast measured
against every shipped theme, is in [docs/contrast.md](docs/contrast.md).

| Action | What it does |
|---|---|
| Expand | Fetches up to 100 neighbours that are not already drawn. |
| Collapse | Removes what hangs only from this node. |
| Dismiss | Removes the node from the canvas. |
| Inspect | Opens the node's labels, id and properties, exact and complete, with Copy JSON. |
| Connect nodes | Draws the relationships among the nodes already on the canvas. |
| Find path | Between two selected nodes, tried at increasing depth up to 10. A node that cannot answer says so; "no path found" names the depth it searched. |
| Show more nodes | Adds nodes the first draw left out. |

The canvas holds at most 1,000 nodes and 2,000 relationships; a result opens with
the first 300 nodes and says how many it left out. Every query the app writes
itself (a label preview, expand, connect, path) passes values as parameters, never
spliced into the text, and uses the form each engine proves to work.

**Layout** is computed off the main thread, in a Web Worker running d3-force with
a fixed seed, so the same result lays out the same way, and the worker is stopped
when a newer layout replaces it. If the worker cannot run, the nodes are placed
on a grid and a notice says so. The page never falls back to computing the layout
on the main thread.

**Keyboard.** The canvas is a single tab stop with roving focus: arrow keys move
to the connected node in that direction, Enter inspects, Space selects, `E`
expands, `C` collapses, Delete dismisses, `P` finds a path between two selected
nodes, `?` lists every key, Tab leaves the canvas. Each node is spoken with its
caption, labels and how many relationships are shown, and each action is
announced through one polite live region. Animations respect the reduced-motion
setting. The Table tab lists the same result for anyone who would rather not use
the canvas.

## The sidebar

For the active connection the sidebar lists its **node labels** and
**relationship types**, each with its properties and the types observed for
them, and a count where the node has one. A count marked *about* is the
database's estimate. Selecting a label or type shows and runs a preview of 25
rows in the workbench. **Refresh** asks the node to read the database again.

The line under the tree says how far the schema can be trusted: how long ago it
was read, that property keys are **sampled** from a few nodes per label (so a
property can exist that is not listed), that a refresh failed and the last good
snapshot is shown, or that an older node reports a schema it cannot refresh. An
empty schema from a node that cannot report one is never presented as an empty
graph.

## Ask

The Ask box asks the node's language model (`get_query`) to write Cypher. What
comes back is a **preview**: it is put in the editor and **not run**; you read it,
edit it, and press Run. The node has already checked that it reads only, and the
text check runs on it again. An answer in words is shown as an answer. A pipeline
with no language model gets a note that says so instead of an error. **Stop
waiting** drops a late answer.

## History

Each statement you run is recorded per connection in your RocketRide workspace
file on the server, not in this browser: its text as typed (including any
literal values), when, how long it took, how many rows, and how it ended. You can
search, pin, add a note, load a statement into the editor, run it again (an
explicit action), delete entries, clear all, or turn recording off per
connection. Up to 100 entries and 8 KiB of text per entry are kept. Tokens and
connection strings are never recorded.

## The write console

A connection whose node reports `allow_execute` and supports the graph result
shape has a **Write console** button. It is a separate document with its own
editor and an **Execute** button, and it always says what it is:

- Before anything is sent, a confirmation lists the statements that look like
  they change data, with their text, and says **This is a text check, not a
  database safeguard.** There is no "do not ask again".
- Statements go through `execute` with the graph result shape, so what a
  statement returned is drawn like any other result.
- Each statement is its own request. A batch stops at the first error; statements
  that ran are not undone. The strip says how many ran and how many were not run.
- A write is never sent again by the app: no automatic retry.

## Safety

- The browse editor, Ask, the sidebar previews and every graph action use
  `read_query`, which the node runs read-only whatever the node allows
  elsewhere. A node that cannot do that is not browsable.
- The text check that refuses writes in the browse editor is a convenience and
  can be wrong in both directions. It is not a boundary.
- **The boundary is the database role.** Connect the node with a user that can
  only read, and a statement the app should never send cannot do harm. On Neo4j
  the node reads in a read session, which is a routing hint, not access control;
  Apache AGE reads in a read-only transaction; FalkorDB uses `GRAPH.RO_QUERY`.
  The drawer states which of these a connection has and whether the node verified
  its own permissions (`read_boundary_verified`).
- Nothing the app saves or shows contains a task token, a connection string or a
  password.

## Limits

- It reads and writes through the node's tool surface: no cancel of a running
  query, no server-side cursor, no streaming of a large result. A query is
  bounded by the row limit, the node's element and value budgets and its
  statement timeout.
- It does not edit the graph's schema, import or export data, or draw a result
  that has no nodes.
- Apache AGE 1.5.0 lacks `date()`, `duration()` and `EXISTS { }` subqueries; the
  node says so with its own text and the app shows it.
- FalkorDB and Neo4j refuse two columns with the same name; AGE keeps them, and
  the Table shows both.
- Only Chromium has been exercised. The build targets Chrome 81, Edge 83,
  Firefox 76 and Safari 13 and later, but behaviour in Firefox and Safari has not
  been checked, and the layout worker's cross-origin handling differs by browser.
- The code editor needs `cdn.jsdelivr.net`; without it the plain text box is
  used.

## For developers

- App id `rocketride.graph`, development port 3102. The code under `src/graph`,
  `src/cypher` and `src/layout` is plain TypeScript with no browser or shell
  dependency, so it runs under `node:test`. The shared Explorer library
  (`apps/shared/src/explorer`) provides discovery, the tool session, history and
  the statement runner.
- `./builder graph-ui:test` type-checks `src` and `tests`, then runs every file in
  `tests/`; a file that is missing from the list in `scripts/tasks.js`, or an empty
  run, fails the task. `tests/fixtures/v1/live/` holds answers captured from the
  real node tools on Neo4j, FalkorDB and Apache AGE; `tests/fixtures/provisional/`
  is hand-modelled and kept for the cases the live set does not cover.
- `./builder graph-ui:build` bundles the app, registers it and copies it to the
  served directory. Rebuilding an app at the same version needs the engine's
  store reset before the server serves it again.
