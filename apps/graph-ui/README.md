# Graph Explorer

Graph Explorer is the app for working with a graph database your pipelines
already talk to. It is not a database client of its own: every query travels
through a graph tool node inside one of your running pipelines, so it reaches
exactly the graph that node is configured for, with that node's permissions.
If apps are new to you, read [Apps](../../docs/public/product/concepts/apps.md)
first.

The supported nodes are [`rocketride_graph`](../../nodes/src/nodes/rocketride_graph/README.md)
(Apache AGE), [`graph_neo4j`](../../nodes/src/nodes/graph_neo4j/README.md) and
[`graph_falkordb`](../../nodes/src/nodes/graph_falkordb/README.md).

This README grows with the app; sections for each capability are added as the
capability lands.
