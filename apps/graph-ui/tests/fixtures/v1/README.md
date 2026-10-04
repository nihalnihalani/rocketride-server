# CONTRACT v1 goldens — DRIVER-GENERATED rows (graph-backend, commit 65860bd6d)

Rows are produced by the real normalizer from REAL driver objects (Neo4j entities via
the neo4j 6.3.1 driver's own Bolt hydration, FalkorDB values via falkordb-py 1.7.0's
reply parser, AGE values from agtype text as psycopg2 returns it). Generator:
../gen_v1_driver.py (uses nodes/test/test_graph_drivers_full.py builders).

Envelope fields (row_limit/truncated/...) follow read_query semantics but were filled
by the generator; they will be regenerated from the real read_query tool path after G09.
Logical graph = provisional one: Alice(Person,Employee on neo4j/falkordb; Person on AGE),
Bob, Acme; KNOWS x2 parallel, reverse KNOWS, LIKES self-loop, WORKS_AT; path p walks
k1 backwards (nodes in traversal order, relationship start/end = stored direction).
AGE fixture has a duplicate 'name' column. *_types.json cover typed values per driver.
