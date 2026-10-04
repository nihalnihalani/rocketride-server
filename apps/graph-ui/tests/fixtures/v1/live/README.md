# CONTRACT v1/v1.1 wire fixtures captured from the REAL tool path (graph-backend)

Captured 2026-10-04 by ../../gen_v1_live.py from the real node tools (read_query, dialect,
get_schema, refresh_schema, error text) running on the real neo4j 6.3.1 / falkordb 1.7.0 /
psycopg2 drivers against the local disposable containers: Neo4j 5.26.31 Community,
FalkorDB 6.0.1, PostgreSQL 16.3 + Apache AGE 1.5.0. Backend commits: G09 6ed45a150,
G10 d14603b9f, 7e44183bb. Only the engine surface (rocketlib, config) was stubbed.

- *_read_query_*.json: exact envelopes (all 9 fields), incl. AGE duplicate column 'a.name',
  AGE id 11821949021847553 (> 2^53) as string + number tag, path traversal vs stored
  direction, Neo4j byte[] -> bytes tag, truncation by rows.
- *_dialect.json: v1 dialect (engine/version/edition, database/graph, capabilities,
  limits, read_boundary, read_boundary_verified). No hosts or credentials.
- *_get_schema.json: legacy keys + schema v2 block. Neo4j's includes other test data
  present on the shared server (realistic noise).
- age_refresh_schema_stale.json: a failed refresh (budget forced to 0): last good schema
  kept, stale: true, error set.
- *_errors.json: str(exception) = "headline\ndetail" for refusals, AGE hints, timeouts,
  invalid input, DB errors, execute disabled.
Neo4j element ids embed the container's database UUID (local throwaway value).
