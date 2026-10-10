# Second re-review ping (user-requested, 2026-09-11)

One short comment per PR, mentioning only the reviewers whose review state gates that PR.
`3626e659` = develop tip SHA at posting time (merge-tree re-verified in the same step).

## #683 → @asclearuc @joshuadarron @dsapandora

@asclearuc @joshuadarron @dsapandora — requesting re-review on `3dc37c65`. Since your last reviews the branch was synced to develop by merge commit (no history rewritten), CodeRabbit's three Sep-7 findings were fixed with regression tests (dataset prompt reset, evaluator metadata carry-through, evaluator shim path), and develop's new icon gate is satisfied. `CI OK` is green ([run 34492100993](https://github.com/rocketride-org/rocketride-server/actions/runs/34492100993)), all 58 review threads are resolved, and the branch merges cleanly onto the current develop tip (`3626e659`). The one item I cannot close from my side is the real-engine scoring run with a model credential (asclearuc's acceptance criterion); I can hand over the exact command if someone with a credential can run it. Full details: [summary comment](https://github.com/rocketride-org/rocketride-server/pull/683#issuecomment-5621661633).

## #1489 → @dsapandora

@dsapandora — requesting re-review on `90b8e247`. Your empty-catalogue concern is addressed: the catalogue is read through the engine's service registry (`rocketlib.getServiceDefinitions()` / `getServiceDefinition()`) instead of the filesystem, and an empty or failed read now yields a conservative limit (the smallest known context window; 8192 if nothing is known) instead of an optimistic 128k. 171 tests pass, `CI OK` is green ([run 34487046212](https://github.com/rocketride-org/rocketride-server/actions/runs/34487046212)), all threads are resolved, and the branch merges cleanly onto the current develop tip (`3626e659`). Full details: [summary comment](https://github.com/rocketride-org/rocketride-server/pull/1489#issuecomment-5620930259).

## #1607 → @dsapandora

@dsapandora — your approval was dismissed by the develop sync; requesting re-review on `b2d6d5bd`. The change since the approved head is the port of `diff` to develop's rewritten CLI (`setup_parser()`/`_dispatch()`, `async run_diff`) with behavior held fixed; the only inherited change is the `--uri` default now following develop's shared helper. `CI OK` is green ([run 34488896663](https://github.com/rocketride-org/rocketride-server/actions/runs/34488896663)), 0 unresolved threads, clean merge onto the current develop tip (`3626e659`). Full details: [summary comment](https://github.com/rocketride-org/rocketride-server/pull/1607#issuecomment-5621372999).

## #1581 → @dsapandora

@dsapandora — your approval was dismissed by the develop sync; requesting re-review on `be41c2e0`. Since the approved head: `eval` ported to develop's rewritten CLI with behavior held fixed, plus a follow-up for CodeRabbit's re-review (spec-run failures now carried into the JSON/JUnit/human reports, exit-code wording aligned everywhere, eval `--token` docs removed), each item verified by CodeRabbit. `CI OK` is green ([run 34502903010](https://github.com/rocketride-org/rocketride-server/actions/runs/34502903010)), 0 unresolved threads, clean merge onto the current develop tip (`3626e659`). Full details: [summary comment](https://github.com/rocketride-org/rocketride-server/pull/1581#issuecomment-5621373826).

## #1612 → @dsapandora

@dsapandora — your approval was dismissed by the develop sync; requesting re-review on `1d16eed5`. Since the approved head: `otel` ported to develop's rewritten CLI with behavior held fixed (the `_add_connection_args(json_arg=...)` hunk is byte-identical to #1581's, so whichever lands second auto-merges), with develop's README-clients relocation and the otel-bridge link fix re-applied. `CI OK` is green ([run 34488937607](https://github.com/rocketride-org/rocketride-server/actions/runs/34488937607)), 0 unresolved threads, clean merge onto the current develop tip (`3626e659`). Full details: [summary comment](https://github.com/rocketride-org/rocketride-server/pull/1612#issuecomment-5621619274).
