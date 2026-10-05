#!/usr/bin/env bash
# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================
# Graph Explorer validation: every repository gate the feature touches, with real
# builder actions only. Run from the repository root. Each step logs to
# $LOGS/<step>.log and records its exit status; the script never stops early and
# never hides a failure. It does not run the live SDK or browser lanes (see
# README.md in this folder).
#
# Prerequisites: the database containers from README.md (the nodes:test and
# nodes:test-db steps require them via RR_REQUIRE_DB_TESTS=1).
#
# Environment:
#   OUT_DIR       where the logs go (default: out/ next to this script, git-ignored)
#   STORE_DIR     disposable engine store for the test servers the builder starts
#                 (default: a new temporary directory). Without RR_STORE_URL the
#                 engine writes into ~/.rocketlib/store.
#   UV_CACHE_DIR, SDKROOT, CI  passed through when set (macOS builds may need SDKROOT).
set -u
OUT_DIR=${OUT_DIR:-$(cd "$(dirname "$0")" && pwd)/out}
LOGS=${LOGS:-$OUT_DIR/validate-$(date +%Y%m%d-%H%M%S)}
STORE_DIR=${STORE_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/rr-validate-store.XXXXXX")}
mkdir -p "$LOGS"
export CI=${CI:-true}
export RR_STORE_URL=filesystem://$STORE_DIR
SUMMARY=$LOGS/SUMMARY.txt
: > "$SUMMARY"
echo "revision $(git rev-parse HEAD) dirty=$(git status --porcelain | grep -v constants.ts | wc -l | tr -d ' ')" | tee -a "$SUMMARY"
echo "store $RR_STORE_URL" | tee -a "$SUMMARY"

step() {
	local name=$1; shift
	"$@" > "$LOGS/$name.log" 2>&1
	local rc=$?
	# The builder rewrites this file during builds; never leave it modified.
	git checkout -- packages/client-typescript/src/client/constants.ts 2>/dev/null
	printf '%-28s exit=%s\n' "$name" "$rc" | tee -a "$SUMMARY"
}

# Frontend unit + type gates
step shared-test        ./builder shared:test
step sql-ui-test        ./builder sql-ui:test
step graph-ui-test      ./builder graph-ui:test
step shell-check        ./builder shell:check shell:test
# SDKs (frozen-surface tsc runs inside client-typescript:test)
step client-ts-test     ./builder client-typescript:test
step client-py-test     ./builder client-python:test
# Python: engine-side suites, graph suites, live databases (required, not skippable)
step ai-test            ./builder ai:test
step nodes-test-db      env RR_REQUIRE_DB_TESTS=1 ./builder nodes:test-db
step nodes-test         env RR_REQUIRE_DB_TESTS=1 ./builder nodes:test
# Node README + docs gates
step node-readmes       python3 scripts/validate-node-readme.py nodes/src/nodes/graph_neo4j nodes/src/nodes/graph_falkordb nodes/src/nodes/rocketride_graph nodes/src/nodes/rocketride_sql nodes/src/nodes/db_postgres
step docs-validate      ./builder docs:validate
step docs-check         node scripts/build.js docs:check
step docs-build         ./builder docs:build
# Production app builds, then the full distribution
step apps-build         ./builder sql-ui:build graph-ui:build
step full-build         ./builder build

echo "logs: $LOGS" | tee -a "$SUMMARY"
grep -c 'exit=0' "$SUMMARY" | xargs -I{} echo "{} steps passed" | tee -a "$SUMMARY"
