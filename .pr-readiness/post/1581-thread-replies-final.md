# #1581 — thread replies for CodeRabbit's re-review of 8e7ef723 (final text)

Post via REST `POST repos/rocketride-org/rocketride-server/pulls/1581/comments/<root>/replies --input <json>`
after the follow-up head is pushed and its CI has concluded. `be41c2e0` = pushed follow-up SHA (8 chars).

## T1 (root 3980191483, thread PRRT_kwDOROCxS86hHbbK) — docs list `--token` for eval

Good catch — fixed in `be41c2e0`. `eval` registers only `--uri`/`--apikey` (`_add_connection_args(eval_parser, json_arg=False)`), and `run_eval` passes just those to `connect_client`, so `--token`/`ROCKETRIDE_TOKEN` never applied here. Removed from the eval section of `docs/README-python-client.md` and from `packages/client-python/docs/index.md` — those were the only two eval mentions; `upload`/`status`/`stop`/`events` keep theirs, since they genuinely take `--token`. Verified against the real parser: `rocketride eval --help` lists exactly `-h, --uri, --apikey, --case, --fail-fast, --json, --junit`.

## T2 (root 3980191498, thread PRRT_kwDOROCxS86hHbbX) — spec execution errors missing from machine reports

Fixed in `be41c2e0` — you're right that this could publish a green artifact for a failed run. Spec-run failures are now collected as `SpecError` records (path, message, exception type) and threaded through all three renderers: `render_json` gains a top-level `spec_errors` list plus `summary.spec_errors` (both always present, so consumers need not probe for the key); `render_junit` emits a one-test `<testsuite>` with an errored `<testcase>`, counted in the `<testsuites>` totals; `render_human` lists them and appends `, N spec error(s)`. stderr output and the 0/1/2 contract are unchanged, including all-specs-errored → 2, whose reports now carry the errors. 14 new tests (5 CLI, 9 reporter); with the three source files (`reporters.py`, `eval.py`, `evals/__init__.py`) reverted, 6 of the CLI tests fail and the reporter tests no longer import.

## T3 (root 3980191515, thread PRRT_kwDOROCxS86hHbbi) — exit code 1 under-documented

Done in `be41c2e0`: the parser description now reads `1 = at least one case failed or a spec could not run to completion`, and the `test_eval_cli.py` module contract uses the same definition. The same sentence is also updated everywhere else it appears — `eval.py`'s `Exit Codes:` docstring block, both docs files (`docs/README-python-client.md`, `packages/client-python/docs/index.md`) and the CLI reference page (`packages/docs/content-static/cli.mdx`) — so the contract reads identically in all six places. The mapping itself is unchanged — a spec that raises still exits 1 when another spec produced results, and 2 when no case produced a result at all.
