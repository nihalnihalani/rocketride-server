# Model routing
| Role | Requested (brief) | Configured at spawn | Runtime-reported | Notes |
|---|---|---|---|---|
| Lead / node implementation owner (#1489, #683) | Claude Fable 5.1 (`claude-fable-5-1`) | session model `claude-fable-5-1` (confirmed via /model) | claude-fable-5-1 | — |
| sdk-implementation-engineer (#1612 #1607 #1581) | Claude Opus 5 (`claude-opus-5`) | Agent tool `model: opus` (family alias; exact release not exposed) | not exposed | only the configured alias is known |
| review-and-test-engineer | Claude Sonnet 5 (`claude-sonnet-5`) | Agent tool `model: sonnet` | not exposed | only the configured alias is known |
| independent-verifier | Claude Opus 5 (`claude-opus-5`) | Agent tool `model: opus` (to be spawned after candidates exist) | not exposed | only the configured alias is known |
Limitations: this session's runtime does not expose the interactive agent-teams shared task list or direct teammate messaging (SendMessage/TaskCreate unavailable), so the team runs as named, model-pinned teammates in coordinated waves via the Agent tool; coordination flows through the lead and the shared `.pr-readiness/` ledger. Effort level per teammate is not exposed. No global/account settings were changed.
Waves actually run: sdk-implementation-engineer (opus) + review-and-test-engineer (sonnet) in parallel; independent-verifier wave 1 (opus) on the lead's #683/#1489 candidates; wave 2 (opus) on the CLI trio after the engineer reports. The lead did not self-certify: both lead candidates went to the verifier before any push.
Final: independent-verifier ran three waves (1, 1b, 2) plus the lead's own spot-checks; every push happened only after a verifier ACCEPT. No model substitution was required; runtime-reported model ids for subagents are not exposed by the Agent tool (aliases opus/sonnet were the configured values).
