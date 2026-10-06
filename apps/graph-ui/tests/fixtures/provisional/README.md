# PROVISIONAL CONTRACT v1 wire fixtures (hand-modelled)

Hand-modelled from CONTRACT v1, NOT produced by driver objects or the node tools, and
not regenerated or checked by CI. The generated sets are in `../v1/` (driver goldens)
and `../v1/live/` (captures of the real tool path), both from
`nodes/test/graph_wire_fixtures.py`; graph-ui's tests keep these for the cases those
sets do not cover (truncation by elements, an exact-limit result, scalars, pre-upgrade
nodes, schema states).

Ids are sentinels: Neo4j elementId strings, FalkorDB small decimal strings, AGE
17-digit graphids incl. 11821949021847553 (> 2^53). Same logical graph on all three:
Alice(Person[,Employee]) -KNOWS-> Bob twice (parallel), Bob -KNOWS-> Alice (reverse),
Alice -LIKES-> Alice (self), Alice -WORKS_AT-> Acme; path p traverses Bob<-Alice->Acme
(traversal order in nodes, STORED direction in start/end). User map `meta` shows @-key
escaping ('@@kind' on the wire == '@kind' in the user's data; strip exactly one '@').
AGE fixture has a duplicate column 'name'. errors.json headline/detail split on the
first newline. dialect_old_node.json / schema_old_node.json = pre-upgrade nodes.
