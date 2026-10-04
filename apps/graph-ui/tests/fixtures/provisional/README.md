# PROVISIONAL CONTRACT v1 wire fixtures (graph-backend)

Hand-modelled from CONTRACT v1, NOT produced by driver objects. Replace with the
driver-generated goldens in ../v1/ when they land (graph-backend will message you).
Ids are sentinels: Neo4j elementId strings, FalkorDB small decimal strings, AGE
17-digit graphids incl. 11821949021847553 (> 2^53). Same logical graph on all three:
Alice(Person[,Employee]) -KNOWS-> Bob twice (parallel), Bob -KNOWS-> Alice (reverse),
Alice -LIKES-> Alice (self), Alice -WORKS_AT-> Acme; path p traverses Bob<-Alice->Acme
(traversal order in nodes, STORED direction in start/end). User map `meta` shows @-key
escaping ('@@kind' on the wire == '@kind' in the user's data; strip exactly one '@').
AGE fixture has a duplicate column 'name'. errors.json headline/detail split on the
first newline. dialect_old_node.json / schema_old_node.json = pre-upgrade nodes.
