# DAF-3 prose corrections for #2282 (apply after the revision-5 push; edit in place, no duplicate comments)

## Thread reply r4015934978 (PATCH /pulls/comments/4015934978)
- "each written first and shown failing on the previous code" -> "the behaviour-changing cases were written first and shown failing on the previous code; the remaining rows pin conservative results that already held"
- "`hasTopLevelKeyword` is unchanged; the depth scanner it shared with the nested search is `keywordSites` in split.ts." -> "`hasTopLevelKeyword` keeps its API and its results; its word boundary now uses the SQL identifier class (34fa9963), and the depth scanner it shares with the nested search is `keywordSites` in split.ts."
- Append a sentence for the revision-5 commits (maintainer's classify fix, applyRowLimit sibling, CTE-name grammar) with the new counts.

## Summary comment 5680719023 (PATCH /issues/comments/5680719023)
- "plus an independent review, an adversarial review and a clean-state verification pass on the final head" -> "plus an independent review and a clean-state verification pass on each pushed head, and a dedicated adversarial pass whose final-revision verdict is recorded (its open items were taken in the last push)"
- Update head SHA, commit count, test counts, CI run.

## Description (PATCH /pulls/2282)
- "What changed -> Tests/docs": "`sql-ui:test` (node:test via tsx) with 496 pure-logic tests" -> the final count.
- Testing section: counts and CI run; add the revision-5 items to the "Review round" list; add the DAF-4/5 limitations to "Risks and limitations": history keeps a failed statement's error text; node-originated refusals (`allow_execute`, `max_execute_rows`) still headline as "Database reported: …".
