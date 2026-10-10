# Conflict resolutions (lead-owned PRs; CLI trio recorded in conflict-resolutions-cli.md by the SDK engineer)
| PR | Target SHA | File/region | Competing changes | Chosen behavior | Preserved contracts | Validation | Commit |
|---|---|---|---|---|---|---|---|
| #683 | f9a25cbb | docs/develop/README.md "Further Reading" | develop moved docs/*.md → docs/develop/ and rewrote sibling links; PR added a "Cobalt Pipeline Testing" link at the old path | develop's three sibling links + the PR's link, with the Cobalt doc moved to docs/develop/README-cobalt-testing.md to follow the restructure; nodes/test/cobalt/cobalt.toml reference updated | develop's docs layout; PR's doc discoverability; README-nodes.md catalog rows (auto-merged) | no markers; rows verified; cobalt suite 230 passed | e1f06b4f (merge, per the merge-not-rebase instruction) |
| #1489 | f9a25cbb | — | none (CHANGELOG.md, docs/develop/README-nodes.md auto-merged) | — | — | suite 165 passed post-merge | 9b4cfcce (merge) |
