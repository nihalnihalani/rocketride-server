# Wave 1b independent verification — PR #683, PR #1489 (post-correction)

Verifier: independent-verifier (wave 1b), Claude Opus 5. Read-only toward
GitHub; no pushes; candidates never modified (the two mutation tests below
back up and restore with `cp`, no git).

> **Deliverable location.** The brief's first choice
> (`.claude/worktrees/pensive-kowalevski-be7b32/.pr-readiness/`) is outside this
> agent's worktree and the write is refused by worktree isolation (same as
> wave 1). This report is therefore at the same relative path in **my**
> worktree:
> `/Users/nihalnihalani/Desktop/Github/rocketride-server/.claude/worktrees/agent-aea002dfefff316f5/.pr-readiness/verification-wave1b.md`

Candidates: **#683** `56072ad97a081d1dfa997773f0060e1f495a9303` (parent
`e1f06b4fd`), **#1489** `12d8dc8cae3badfcae7ff3703d2d137385f338da` (parent
`9b4cfcceb`). Both parents byte-identical to the merges wave 1 inspected.

**Verdicts**

| PR | Verdict |
| --- | --- |
| #683 | **PUSH-READY.** Both wave-1 corrections landed correctly; nothing else changed. |
| #1489 | **PUSH-READY after one non-blocking docstring sentence** (item 2). The wave-1 blocker is genuinely fixed and mutation-proved. |

**Floor design ruling: ACCEPT the lead's choice** (reasoning in §1489-4).

Test environment: python 3.12 venv (`pydantic 2.13.5`, `json5`, `pytest 9.1.1`,
`pytest-asyncio`, `ruff 0.16.6`); `sitecustomize.py` on `PYTHONPATH` putting
`sys.modules['engLib'] = MagicMock()`, a no-op `depends` module, and
`rocketlib-python/lib`, `packages/ai/src`, `packages/client-python/src` on
`sys.path`. Sub-worktrees under
`.claude/worktrees/agent-aea002dfefff316f5/wt/{c683,c683pre,c1489}`.

---

# PR #683

## Amendment delta — ACCEPT

`git diff 64571f500 56072ad97` is **exactly the two required corrections and
nothing else**: `nodes/src/nodes/eval_cobalt/README.md` (one line) and
`nodes/test/cobalt/test_eval_cobalt.py:712` (one assertion + two comment
lines). No scope creep.

## (1) Order-independent assertion — ACCEPT

`nodes/test/cobalt/test_eval_cobalt.py:712` now reads

```python
assert not getattr(score_answer, 'metadata', None)
```

Proved order-independent by measuring both bindings the suite can produce:

```
REAL Answer  : metadata = {}    falsy? True   is None? False
Mock Answer  : metadata = None  falsy? True   is None? True

OLD assertion 'is None' passes in both bindings? False
NEW assertion 'not ...' passes in both bindings? True
```

The real schema's `Field(default_factory=dict)`
(`packages/client-python/src/rocketride/schema/question.py:92`) makes `{}` the
"no metadata" state; the mock leaves `None`. The new form accepts both, the old
one only the mock. Correct fix, and the added comment explains why.

## (2) README output contract — ACCEPT

`nodes/src/nodes/eval_cobalt/README.md`, in the **Output** section (the right
place, immediately above the payload table):

> The score answer carries a deep copy of the incoming answer's `metadata` (for
> example the dataset item's `dataset_id` and `expected`), so a downstream
> consumer can join each score to its source item by key rather than by answer
> order, which is not stable across fan-out or parallel workers. Its JSON
> payload has these keys:

Matches the code at `nodes/src/nodes/eval_cobalt/IInstance.py:145-147`
(`if isinstance(metadata, dict): eval_answer.metadata = copy.deepcopy(metadata)`).
Satisfies the co-located documentation rule in `.claude/CLAUDE.md`.

## (3) Test runs — ACCEPT

| Run | Result |
| --- | --- |
| `pytest -q nodes/test/cobalt` (default order) | **228 passed, 2 skipped, 1 failed** (231 total) |
| three cobalt modules **reversed** (`test_pipeline_metadata_hop`, `test_eval_cobalt`, `test_dataset_cobalt`) | **204 passed, 0 failed** |
| `-k "metadata or empty_text or shim"` | 32 passed |
| `test_score_answer_without_metadata_has_none` in isolation | 1 passed |

231 total reconciles with wave 1's 231 and the lead's 230/1 (the delta is the
env-gated `OPENAI_API_KEY` skip). **No order-dependent failure from this PR's
tests in either direction.**

## (4) The one failure is pre-existing — CONFIRMED

`TestIGlobalLifecycle::test_begin_global_creates_evaluator`
(`Exception: The service eval_cobalt does not have a preconfig section`,
`packages/ai/src/ai/common/config.py:259`) **fails identically at the parent
merge `e1f06b4f`**: 222 passed / 2 skipped / 1 failed there, same single
failure. The candidate adds exactly +6 tests (2 parametrised `empty_text`,
`carries_incoming_metadata`, `without_metadata_has_none`, 2 shim tests) →
228. **Not introduced by this candidate.** It also passes in the reversed
order, confirming wave 1's mock-pollution diagnosis.

## (5) Lint — ACCEPT

`ruff check` → *All checks passed!*; `ruff format --check` → *30 files already
formatted* (over `dataset_cobalt/`, `eval_cobalt/`, `nodes/test/cobalt/`).

## (6) Merge fidelity — unchanged from wave 1, re-confirmed

Merge base `d5e38780b`. Develop changed 560 files since the fork; the merge
brought 562 onto the PR; `comm -23` empty (no develop content lost); the two
extras are the deliberate conflict resolution
(`docs/develop/README-cobalt-testing.md`, `nodes/test/cobalt/cobalt.toml`).
No conflict markers.

## PR #683 — required changes

**None.** Push-ready.

*Cosmetic only (do not block):* the test is still named
`test_score_answer_without_metadata_has_none` though it now asserts falsiness
rather than `None`; `..._has_no_metadata` would read truer.

---

# PR #1489

## (1) Envelope unwrap — ACCEPT

Code at `nodes/src/nodes/context_optimizer/optimizer.py:270-276`:

```python
if not isinstance(raw, dict):
    return {}
# Unwrap the envelope; a bare index (no ``services`` member) is tolerated.
index = raw.get('services') if 'services' in raw else raw
if not isinstance(index, dict):
    return {}
```

**Re-measurement against the real engine shape** (registry rebuilt from the
source tree, served as `{"services": {...}, "version": 7}`, every rocketlib
call instrumented):

```
registered logical types parsed from disk : 177
  of which publish preconfig.profiles      : 165

REAL envelope {"services":..,"version":..}
   catalog entries           : 455
   getServiceDefinition calls: 177
   lookups of envelope keys  : 0   []
   unknown-model budget      : 8191

BARE index (tolerance path)
   catalog entries           : 455      (identical)
   lookups of envelope keys  : 0   []
```

455 entries and 0 envelope-key lookups — matching the brief's expectation, and
177 per-type calls (the brief's "~180"). Every unusable shape returns `{}`
**without fetching anything**:

```
None / 'not-a-dict' / [] / 42 / {'services':'x',...} / {'services':None} / {'services':[]} / {}
   -> catalog {}   (getServiceDefinition never called)
```

**Collision hazard checked and clear:** no registered logical type is literally
named `services` or `version`, so the `'services' in raw` heuristic cannot
mistake a bare index for an envelope today.

**Mutation test — the tests genuinely guard the fix.** Reverting the unwrap to
`index = raw` (the wave-1 bug) fails **13 tests**, including
`test_registry_envelope_is_unwrapped` and all three envelope parametrisations
`test_unusable_registry_index_yields_empty_catalog[raw4/5/6]`. File restored
by `cp` and verified clean (`git status --short` empty).

**C++ contract re-verified independently** (not taken from wave 1):

- `services.cpp:2153-2155` — `res["services"] = _mv(schemas); res["version"] = VERSION;` — the envelope.
- `:2081-2087` — keyed by `def.logicalType`.
- `:2093-2094` — `INTERNAL`-capability services skipped.
- `:2090` `ServiceName`, `:2097-2101` `ServiceCat`.
- `bindings.cpp:493-505` — `getServiceDefinitions` returns `jsonToDict(services)` with **no unwrapping**, and `py::none()` on a falsy result (covered by the `isinstance(raw, dict)` guard).
- `bindings.cpp:468-484` — `getServiceDefinition` returns the raw `serviceDefinition`, `py::none()` when absent (covered by `isinstance(definition, dict)`).

## (2) Docstring — NEEDS-CHANGE (one sentence, non-blocking)

Right: the envelope shape, the `services.cpp` / `getServiceSchemas` citation,
"non-INTERNAL", "keyed by logical type", and that the index carries the config
schema rather than `preconfig` (so the second call is required).

**Wrong**, `optimizer.py:245-246`:

> (The engine's ``--serviceCategory`` / ``--serviceName`` modes narrow that
> index for other callers; this node calls it unfiltered.)

Both are **process-level** options — `static application::Opt ServiceName{"--serviceName"}`
and `ServiceCat{"--serviceCategory"}` at `services.cpp:31-32`, read inside
`getServiceSchemas()`. The Python binding takes **no arguments**, so this node
cannot "call it unfiltered"; when the engine is started with those flags this
node gets the same narrowed index as everyone else. Measured by reimplementing
`getServiceSchemas()` lines 2080-2155 exactly:

```
default (no flags)                index keys=177  catalog=455  grok-4-0709 -> 256000 (catalog)
--serviceCategory                 index keys=177  catalog=455  grok-4-0709 -> 256000 (catalog)
--serviceName=llm_openai          index keys=  1  catalog= 84  grok-4-0709 ->   8191 (FELL BACK)
--serviceName=context_optimizer   index keys=  1  catalog=  0  grok-4-0709 ->   8191 (FELL BACK)
```

So the honest statement is the opposite of the current one in both halves:
`--serviceCategory` is **harmless here** (it rewrites the index *values*, and
this node reads only the keys), while `--serviceName` **does** hit this node —
the catalog collapses and real ids silently resolve to the conservative floor
instead of their true window. Safe (errs low, never high), but silent, which is
exactly the caveat wave 1 asked to be surfaced. As written the docstring tells
a future reader the caveat does not apply.

**Exact replacement for lines 245-246:**

```
        (``--serviceCategory`` rewrites the index *values* and so does not
        affect this node, which reads only the keys; ``--serviceName``,
        however, narrows the index to a single entry for every caller
        including this one -- the catalog is then near-empty and known ids
        fall back to :meth:`conservative_model_limit`, quietly but never
        above a real window.)
```

## (3) Tests — ACCEPT

All five items the brief named are present and effective:

| Item | Evidence |
| --- | --- |
| `_install_registry` serves the real envelope by default | signature `envelope=True`; returns `{'services': index, 'version': 'test'}` |
| `test_registry_envelope_is_unwrapped` asserts only real types are fetched | asserts `fetched == ['llm_env']` with the message "the envelope keys must never be looked up as types" |
| unusable-index parametrisation includes envelope variants | 3 added: `{'services':'not-a-dict',...}`, `{'services':None,...}`, `{'services':[],...}`; `getServiceDefinition` is a `pytest.fail` tripwire |
| `test_bare_index_is_tolerated` | present, `envelope=False` |
| `test_non_llm_windows_are_catalogued_but_never_lower_the_floor` | present; asserts the embedding id resolves to 2048 **and** `conservative_model_limit() > 2048` |

**Mutation test 2 — the floor filter is guarded.** Removing the
`_is_llm_class` condition from `_llm_class_min_window` fails **exactly one**
test: `test_non_llm_windows_are_catalogued_but_never_lower_the_floor`. Precise
guard, no over-coupling. File restored and verified clean.

*Nit:* `test_all.py:157` comment names the production path
`_engine_llm_definitions`; the method is `_engine_model_definitions`.

## (4) The conservative floor — **ACCEPT the lead's design**

The lead chose `conservative_model_limit() = min(chat-LLM-class registered
windows ∪ MODEL_LIMITS.values())`, constant only if both are empty. Measured on
develop:

```
_llm_class_min_window = 8191   from  llm_openai/gpt-4, llm_mistral/codestral-latest,
                                     llm_mistral/mistral-medium-2505
min(MODEL_LIMITS)     = 8191   from  gpt-4
conservative_model_limit() = 8191    (both paths agree)
CONSERVATIVE_MODEL_LIMIT_FLOOR = 8192 (only if both empty)
```

Embedding and vision windows are catalogued for lookup and **do not** reach the
floor: `text-embedding-004` → 2048, `text-embedding-005` → 2048, `moondream` →
2048 all resolve by id, yet the floor stays 8191.

**Ruling: ACCEPT.** I could not construct a concrete failure the lead's choice
introduces that the colleague's `MODEL_LIMITS`-only alternative avoids. On
develop both produce 8191, so the question is entirely about futures, and there
the lead's design strictly dominates:

- **The decisive argument, which neither party made: the lead's design
  preserves an invariant the colleague's breaks — a typo must never be budgeted
  higher than the correct spelling.** Under `MODEL_LIMITS`-only, once a chat
  model with a 4096 window is registered, `resolve_model_limit('that-model')`
  → 4096 while `resolve_model_limit('taht-model')` → 8191. The unknown-id
  budget would then exceed a window the node itself resolves — precisely the
  "erring high costs the request" failure the review named. The candidate's own
  `test_unknown_model_never_exceeds_a_catalogued_window` (registry with a 4096
  chat model → budget 4096) pins this behaviour.
- The colleague's objection — that a `min()` over the catalog makes an
  *embedding* input limit the prior for an unknown *chat* model — was valid
  against the earlier unfiltered version and is **answered** by `_is_llm_class`
  (measured above: 2048 is lookup-only).
- The residual exposure of the lead's design is registry drift: if a genuinely
  small chat model is ever registered under `llm_*`, the floor drops for all
  unknown ids and RAG budgets shrink. That is the *intended* semantics rather
  than a defect — a real chat window that small makes low budgeting correct —
  and it degrades utility, never correctness. `max_context_tokens` remains the
  escape hatch and the one-time warning names the id.
- The union with `MODEL_LIMITS` can only lower the result versus LLM-class-only
  and guarantees the floor is defined with an empty registry. No harm.
- Wave 1's rejected clamp alternative is independently re-confirmed wrong:
  three real chat models publish **8191**, below the 8192 constant
  (`gpt-4`, `codestral-latest`, `mistral-medium-2505`).

## (5) README.md:31 — ACCEPT

Line 31 states the conservative fallback is "**8 191 tokens on develop today,
from the gpt-4-class entries**", which matches the measured
`conservative_model_limit() == 8191`, and correctly adds "Embedding input
limits and vision models are catalogued for lookup but never lower this floor."
The `ROCKETRIDE:GENERATED:PARAMS` block spans lines 61-83; the changed lines
(29, 31) are outside it. `services.json` untouched.

*Nits (non-blocking):* "gpt-4-class" names the window size rather than the
vendors — `gpt-4` is the `MODEL_LIMITS` contributor, but two of the three
catalog contributors at 8191 are Mistral. And README line 29 still says the
table "covers deployments where the `llm_*` nodes are not present **next to
this one**" — leftover sibling-directory language now that discovery is
registry-based.

## (6) `_is_llm_class` coverage — ACCEPT, no blind spot

Measured across all 177 registered logical types:

- **16 counted toward the floor**, and every one satisfies **both** signals —
  `llm_*` prefix *and* `classType: ["llm"]`. The two conditions are fully
  redundant on develop today; either alone would give the same answer.
- **Zero** logical types carry `classType` containing `llm` without an `llm_*`
  name; **zero** `llm_*` logical types lack `classType: ["llm"]`. No leak in
  either direction.
- **The `llm_vision_*` trap is handled.** The four directories
  `llm_vision_{gemini,mistral,ollama,openai}` resolve via their `protocol` to
  logical types `image_vision_*` with `classType: ["image"]` — so they are
  **excluded from the floor** (they would otherwise drag it to `moondream`'s
  2048) while their ids remain **resolvable in lookup**
  (`moondream` 2048, `llava:13b` 4096, `gpt-4.1`, `gemini-2.5-pro`, …). This is
  exactly the case wave 1 flagged and the naming discrepancy it noted.
- `llm_openai_api/` contributes **two** logical types (`llm_openai_api` and
  `llm_nebius`, two `services*.json` files); both are counted.

## (7) Suite and lint — ACCEPT

`pytest -q nodes/test/context_optimizer` → **171 passed, 1 skipped** (skip: the
tiktoken-stub encoding test), exactly as expected. `ruff check` → *All checks
passed!*; `ruff format --check` → *7 files already formatted*.

## (8) Merge commit `9b4cfcce` — ACCEPT (spot-check)

Merge base `d956cb169`. Develop changed **561** files since the fork; the merge
brought **561** onto the PR; `comm -23` empty — nothing dropped. No conflict
markers. The fix commit touches exactly three files (`optimizer.py`,
`README.md`, `test_all.py`).

## PR #1489 — required changes

1. **`nodes/src/nodes/context_optimizer/optimizer.py:245-246`** — replace the
   `--serviceCategory` / `--serviceName` sentence with the text in §2 above.
   Non-blocking; everything else is push-ready.

*Optional:* `test_all.py:157` `_engine_llm_definitions` →
`_engine_model_definitions`; README line 29 "next to this one"; README line 31
"gpt-4-class".

---

## Reproduction

Sub-worktrees created by this verifier (safe to remove):

```
.claude/worktrees/agent-aea002dfefff316f5/wt/c683      -> 56072ad97  (candidate)
.claude/worktrees/agent-aea002dfefff316f5/wt/c683pre   -> e1f06b4fd  (pre-fix merge)
.claude/worktrees/agent-aea002dfefff316f5/wt/c1489     -> 12d8dc8ca  (candidate)
```

Probe and mutation scripts live in the verifier scratchpad
(`probe1489.py`, `probe_llmclass.py`, `probe_enginemodes.py`, `probe_8191.py`,
`mutate.sh`, `mutate2.sh`) and are reproducible from the commands quoted
inline. Both mutation scripts back up with `cp` and restore on exit; both
candidates were verified clean (`git status --short` empty) afterwards.
