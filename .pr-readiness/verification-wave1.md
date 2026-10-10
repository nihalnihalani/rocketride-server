# Wave 1 independent verification — PR #683, PR #1489

Verifier: independent-verifier (wave 1). Read-only toward GitHub; no pushes.
Candidates inspected from the shared object store; tests run in isolated
sub-worktrees under `.claude/worktrees/agent-a007c49ad51eaf9e4/wt/`.

> Deliverable location: the brief's first choice
> (`.claude/worktrees/pensive-kowalevski-be7b32/.pr-readiness/`) is outside this
> agent's worktree and writes there are refused by isolation, so this report is
> at the same relative path in **my** worktree:
> `/Users/nihalnihalani/Desktop/Github/rocketride-server/.claude/worktrees/agent-a007c49ad51eaf9e4/.pr-readiness/verification-wave1.md`

**Verdicts**

| PR | Verdict |
| --- | --- |
| #683 `feat/cobalt-pipeline-evaluation-consolidated` | **NOT push-ready** — 2 small required corrections. Substance is sound. |
| #1489 `feature/context-optimizer-node` | **NOT push-ready — blocking.** The central fix does not work against the real engine. |

---

## Provenance (both candidates)

| Check | Result |
| --- | --- |
| `git merge-base --is-ancestor d8ff8f9ed 64571f500` | exit 0 — ACCEPT |
| `git merge-base --is-ancestor f9a25cbbd 64571f500` | exit 0 — ACCEPT |
| `git merge-base --is-ancestor a61e84833 8f820ae91` | exit 0 — ACCEPT |
| `git merge-base --is-ancestor f9a25cbbd 8f820ae91` | exit 0 — ACCEPT |
| `e1f06b4f` parents | `d8ff8f9ed f9a25cbbd` — a real merge, not a rebase (honours asclearuc's MERGE-not-rebase instruction) — ACCEPT |
| `9b4cfcce` parents | `a61e84833 f9a25cbbd` — ACCEPT |

---

# PR #683

## (a) Merge fidelity and conflict resolution — ACCEPT

**No content dropped, either side.** Merge base `d5e38780b`.

```
develop-side changed files (d5e38780b..f9a25cbbd)   : 560
merge brought onto PR head (d8ff8f9ed..e1f06b4f)    : 562
comm -23 (develop changed, merge did NOT bring)     : (empty)   <- no develop content lost
comm -13 (merge brought, develop did not change)    : docs/develop/README-cobalt-testing.md
                                                      nodes/test/cobalt/cobalt.toml
```

Both extras are the deliberate conflict resolution. ACCEPT.

**Only two files were changed by both sides** (`comm -12` of PR-side and
develop-side lists): `CHANGELOG.md` and `packages/client-python/docs/index.md`.
`docs/README.md` was a rename/modify conflict — develop renamed it to
`docs/develop/README.md`, which is the single conflict the lead reported.

**The `docs/develop/README.md` resolution is correct.** `git diff f9a25cbbd
64571f500 -- docs/develop/README.md` shows the PR adds exactly two lines over
develop and removes nothing:

- L112 the inline "Cobalt evaluator suites" sentence
- L119 `- [Cobalt Pipeline Testing](README-cobalt-testing.md)`

Develop's siblings (Build System, Engine Reference, Pipeline Nodes, Pre-commit
Hooks) all survive with their paths correctly rewritten from `../README-*.md`
to `README-*.md` for the new `docs/develop/` location. ACCEPT.

**The doc move is a pure rename.** `git diff --name-status -M d8ff8f9ed
e1f06b4f` reports `R100 docs/README-cobalt-testing.md ->
docs/develop/README-cobalt-testing.md` — 100% similarity, content byte-identical.

**Nothing else linked the old path.** Repo-wide grep for `README-cobalt-testing`
in the candidate returns exactly three hits, all already pointing at the new path:

- `nodes/test/cobalt/cobalt.toml:13`
- `docs/develop/README.md:112`
- `docs/develop/README.md:119`

**The moved file has no relative links of its own** (grep for `](non-http)` in
`docs/develop/README-cobalt-testing.md` returns nothing), so descending one
directory breaks nothing. This was worth checking and the lead did not mention
it; it happens to be safe.

**`README-nodes.md` rows intact.** `git diff f9a25cbbd 64571f500 --
docs/develop/README-nodes.md` shows the `dataset_cobalt` Sources row (with the
column widths re-flowed to match develop's table) and a new `### Evaluation`
table carrying `eval_cobalt`. ACCEPT.

**No conflict markers** anywhere in the candidate (`grep -rnE
'^(<<<<<<<|=======|>>>>>>>)( |$)'` across py/md/json/toml/js/ts/pipe/cpp/h — no
hits).

**CHANGELOG 3-way merge kept both sides**: the PR's `#683` line is present at
its alphabetical position, and develop's new `chat-widget`/`cli` lines are
present.

## (b) CodeRabbit thread 1 — `dataset_cobalt/IInstance.py:72` clear `q.questions`

**ACCEPT (production code).** Fails-before verified.

```
$ pytest ...test_empty_text_clears_template_prompt   # at e1f06b4f, new test copied in
FAILED ...test_empty_text_clears_template_prompt[]
FAILED ...test_empty_text_clears_template_prompt[None]
```

**Challenge — is clearing always correct, and is an empty question worse than
inheriting the template?** I argued it out from the loader and the consumer, and
the answer is that clearing is right.

- `DatasetLoader.to_questions()` (`nodes/src/nodes/dataset_cobalt/dataset_loader.py:389-412`)
  always emits a `text` key, falling back to `''` when the item carries no
  `input`/`text`/`question`. So `'text' in item` is always true and empty text
  is reachable.
- **Without** the fix, such an item emits the *template's* prompt while carrying
  the dataset item's `expected` in metadata. `eval_cobalt` then scores an answer
  to the template question against the dataset item's reference — a measurement
  that is silently, invisibly wrong.
- **With** the fix, the item emits `questions == []`. The downstream `prompt`
  node iterates `for q in question.questions` (`nodes/src/nodes/prompt/IInstance.py:59-61`)
  so it contributes no prompt text, while `merge_metadata` at :69 still carries
  the reference forward. The model answers the instructions alone and the item
  scores near zero — degenerate, but *visibly* so.

Erring toward a content-free question beats erring toward a confidently wrong
score. ACCEPT.

The `contextlib.suppress(ValueError, AttributeError)` guard is adequate:
pydantic v2's `ValidationError` subclasses `ValueError`, and on suppression the
code falls back to the old append behaviour rather than crashing.

*(OPTIONAL, below: no log is emitted when an item is dropped to an empty prompt.)*

## (c) CodeRabbit thread 2 — `eval_cobalt/IInstance.py:~148` deep-copy metadata

**ACCEPT (production code). NEEDS-CHANGE (one new test).** Fails-before verified
for `test_score_answer_carries_incoming_metadata`.

**Challenge — mutation/aliasing, None handling, payload change.** All clean:

- `metadata` is read at `nodes/src/nodes/eval_cobalt/IInstance.py:93` from the
  answer that was *already* deep-copied at :63. The `copy.deepcopy(metadata)` at
  :148 is therefore a copy of a copy — the caller's original answer is doubly
  insulated, and the forwarded answer's metadata is a distinct object from the
  score answer's.
- `isinstance(metadata, dict)` at :147 handles `None` and any non-dict.
- The JSON payload is unchanged: `setAnswer()` at :149-156 still writes exactly
  the four `cobalt_*` keys. `metadata` is a sibling model field, not part of the
  answer body.

**The defect is in the new test, not the code.**
`nodes/test/cobalt/test_eval_cobalt.py:704-712`:

```python
def test_score_answer_without_metadata_has_none(self):
    """No incoming metadata -> the score answer does not fabricate any."""
    ...
    assert getattr(score_answer, 'metadata', None) is None
```

This assertion is **false against the real schema this same PR introduces**.
`packages/client-python/src/rocketride/schema/question.py:92` adds:

```python
metadata: Optional[Dict[str, Any]] = Field(
    default_factory=dict, description='Metadata carried from the originating question or pipeline context.'
)
```

so a fresh `Answer(expectJson=True)` has `metadata == {}`, never `None`. The
test only passes while the module-local `MockAnswer` shadows the real class.
Reproduced both ways:

```
$ pytest "...::test_score_answer_without_metadata_has_none"          -> 1 passed
$ pytest nodes/test/cobalt                                            -> FAILED
E   AssertionError: assert {} is None
E    +  where {} = getattr(Answer(answer={'cobalt_score': 0.0, ...}, expectJson=True,
                                  tokens=None, metadata={}), 'metadata', None)
```

`{}` is the correct "no metadata" state; the production behaviour is fine.

## (d) CodeRabbit thread 3 — `nodes/test/cobalt/evaluators/__init__.py:39` path

**ACCEPT.** Fails-before verified — at `e1f06b4f` the old expression resolved to
`<root>/nodes/nodes/src/nodes` and `test_shim_nodes_dir_exists_and_is_the_node_package_root`
failed on `os.path.isdir`.

**Challenge — do the experiments' imports reach the PRODUCTION package or a
shadowed copy?** Proven: production, for all three evaluators.

```
evaluators.relevance:
   shim module file       = .../nodes/test/cobalt/evaluators/relevance.py
   callable.__module__    = eval_cobalt.evaluators.relevance
   production module file = .../nodes/src/nodes/eval_cobalt/evaluators/relevance.py
   identity ok            = True          (same for grounding and format_check)
```

`pytest nodes/test/cobalt/test_evaluators_shim.py nodes/test/cobalt/experiments`
→ **24 passed**.

## (e) Single-Answer emission contract — ACCEPT

Develop's `f9a25cbbd` ("answers take a single Answer, not a list") is
annotations and docstrings only — its own commit message says so and the diff
confirms it (six `List[Answer]` → `Answer` changes in `__init__.pyi` and
`filters.py`, no runtime code). All three `eval_cobalt` call sites pass exactly
one `Answer`: `IInstance.py:68`, `:140`, `:157`. `dataset_cobalt` passes one
`Question` per `writeQuestions` call. No semantic conflict with the merge.

**Two-answers-per-input is documented** in two places:
`nodes/src/nodes/eval_cobalt/IInstance.py:133-139` (inline) and
`nodes/src/nodes/eval_cobalt/README.md:21` (a bolded bullet naming the
1:1-assumption hazard). ACCEPT.

## (f) Test run — 227 passed / 2 failed / 2 skipped (lead reported 230 / 1)

Totals reconcile: 231 tests both ways. The delta is one env-gated skip
(`OPENAI_API_KEY`, which the lead evidently had set) plus two failures.

1. `test_score_answer_without_metadata_has_none` — **real defect**, see (c).
2. `TestIGlobalLifecycle::test_begin_global_creates_evaluator` —
   `Exception: The service eval_cobalt does not have a preconfig section` at
   `packages/ai/src/ai/common/config.py:259`. **Harness-dependent, pre-existing,
   not introduced by the fix commit.**

**Root cause of both, worth the lead knowing.** `nodes/test/cobalt/test_eval_cobalt.py`
installs its `rocketlib` / `ai.common.*` mocks into `sys.modules` only for the
duration of its own import window (lines 166-188) and then restores the
originals. Whether `eval_cobalt.IInstance` ends up bound to `MockAnswer` +
`MockConfig` or to the real classes depends on which test module imports it
first. The real classes become reachable as soon as
`packages/client-python/src` is importable, because
`packages/ai/src/ai/common/schema/__init__.py:3` re-exports `Answer` from
`rocketride`. The lead's 230/1 is obtainable only when that path is absent — but
the `experiments/` modules require `packages/ai/src` to collect at all, so the
suite is being run in a narrow band of `sys.path` configurations.

## PR #683 — REQUIRED corrections

1. **`nodes/test/cobalt/test_eval_cobalt.py:712`** — the assertion contradicts
   the schema this PR adds. Replace
   `assert getattr(score_answer, 'metadata', None) is None`
   with `assert not getattr(score_answer, 'metadata', None)` (or
   `in (None, {})`), and reword the docstring — `{}` *is* "no metadata" under
   `Field(default_factory=dict)`.
2. **`nodes/src/nodes/eval_cobalt/README.md`** — the score answer now carries a
   copy of the incoming metadata. That is a change to the node's documented
   output contract, and `.claude/CLAUDE.md`'s co-located documentation rule
   requires the doc in the same change. One sentence in the Output/Notes section
   saying the synthetic score answer carries a copy of the incoming metadata so
   consumers can join by key rather than by answer order.

## PR #683 — OPTIONAL suggestions

- `nodes/src/nodes/dataset_cobalt/IInstance.py:75` — emit a `debug()` when
  `text` is empty. Today the item is emitted with no prompt at all and no trace
  of why the score is zero. One line, and it turns a silent degenerate case into
  a diagnosable one.
- The cobalt test modules' import-window mocking (see (f)) is order-dependent
  and will keep producing environment-specific pass/fail sets. Not this PR's
  regression, but a follow-up worth filing.
- `nodes/src/nodes/dataset_cobalt/README.md:14` could note that an item with no
  input text emits a question with no prompt.

---

# PR #1489

## (a) Engine contract — singular ACCEPT, plural **REJECT** — this is the blocker

**The singular half of the lead's claim is correct.**
`packages/server/engine-lib/engLib/store/python/bindings.cpp:468-484`:
`getServiceDefinition(logicalType)` returns
`pyjson::jsonToDict(defPtr->serviceDefinition)`, and
`packages/server/engine-lib/engLib/store/services/services.cpp:1930`
(`def.serviceDefinition = _mv(serviceInfo)`) stores the raw parsed services.json
whole. So the raw definition really does carry
`preconfig.profiles[*].modelTotalTokens`. ACCEPT.

**The plural half is wrong, and the code depends on it.**
`bindings.cpp:493-505` calls `IServices::getServiceSchemas()`, which at
`services.cpp:2153-2155` returns an **envelope**:

```cpp
json::Value res;
res["services"] = _mv(schemas);
res["version"]  = VERSION;
return _mv(res);
```

There is no unwrapping anywhere between C++ and the node:
`rocketlib-python/lib/rocketlib/engine.py:301` is a bare
`getServiceDefinitions = engLib.getServiceDefinitions`.

So `rocketlib.getServiceDefinitions()` returns a dict with exactly two keys,
`"services"` and `"version"`. But `nodes/src/nodes/context_optimizer/optimizer.py:258-273`
does:

```python
index = rocketlib.getServiceDefinitions()
...
for logical_type in index:                       # iterates "services", "version"
    definition = rocketlib.getServiceDefinition(logical_type)   # both -> None
```

**`_engine_model_definitions()` therefore returns `{}` on every real engine.**
The catalog is always empty; the entire registry-based discovery the PR was
asked to build is a no-op in production. Measured directly:

```
registered logical types parsed from disk: 176
  of which publish preconfig.profiles: 168

A) REAL envelope shape  -> catalog entries:   0   getServiceDefinition calls:   2
B) FLAT (test) shape    -> catalog entries: 455   getServiceDefinition calls: 176

REAL envelope:  catalog size 0    unknown-model budget 8191   conservative_model_limit() 8191
FLAT (test):    catalog size 455  unknown-model budget 2048   conservative_model_limit() 2048
                smallest catalog window = ('text-embedding-004', 2048)
```

The repo already contains the correct idiom, in a production consumer of the
same API — `packages/ai/src/ai/modules/task/services_catalog.py:145-146`:

```python
raw = getServiceDefinitions() or {}
services = raw.get('services', {}) or {}
```

Net effect today: the node resolves known ids from the hardcoded
`MODEL_LIMITS` table only, and falls back to 8191 — not 2048 — for unknown ids.
The reviewer's actual ask ("read the catalog through the engine's own services
path") is not yet satisfied.

Two smaller contract caveats the docstring should acknowledge, both from
`getServiceSchemas()`:

- services carrying the `INTERNAL` capability are skipped (`services.cpp:2093-2094`);
- under `--serviceCategory` the per-service entry is replaced by a `sections`
  array (`:2099-2101`), and a `--serviceName` filter reduces the index to one
  entry (`:2090`).

So enumeration is not guaranteed complete, and discovery degrades to a partial
catalog in those modes rather than failing loudly.

## (b) Cost — ACCEPT

`beginGlobal` is invoked from `IPythonGlobalBase::beginFilterGlobal`
(`packages/server/engine-lib/engLib/store/python/python-global.cpp:139-140`) —
once per filter-global, i.e. once per `context_optimizer` node per pipeline
start, not per object. Measured cost of one full 176-definition pass
(Python side; excludes C++ `jsonToDict` marshalling):

```
definitions: 176   approx repr bytes: 630 KiB
one discovery pass: 8 ms -> 455 catalog entries
```

8 ms at pipeline start is defensible; **no pre-filter is warranted** and I would
not recommend one — a name- or classType-based pre-filter is exactly what the
lead correctly rejected, and it would reintroduce the coupling the reviewer
objected to. Worth one comment though: `services_catalog.py:26-30` documents
`getServiceDefinitions` as expensive enough that the server pays it *once per
process*; calling it fresh per pipeline is a deliberate divergence, and saying
so in the docstring pre-empts the next reviewer.

## (c) Conservative floor — NEEDS-CHANGE

**Today the fallback is 8191, not 2048** (measured above), because the catalog
never populates. Once the envelope bug is fixed it silently becomes 2048.

**The lead's attribution is incomplete.** 2048 comes from two places, and the
one that wins is not a chat model:

- `nodes/src/nodes/embedding_openai/services.json:108,116` — `text-embedding-004`
  and `text-embedding-005`. These are **embedding input limits**, not chat
  context windows.
- `nodes/src/nodes/llm_vision_ollama/services.json:124` — `moondream` (the lead
  named `image_vision_ollama`; the file is `llm_vision_ollama`).

**Argued from the review text.** "Erring low costs some unused context; erring
high costs the request" justifies the *direction*, and `max_context_tokens` is a
real escape hatch with a one-time warning, so 2048 is not unsafe. But the
review asked for a conservative fallback, not an arbitrary one: `min()` over an
intentionally unfiltered catalog makes the prior for an unknown *chat* model an
*embedding* model's input limit. At 2048 with the default splits, documents get
1024 tokens — a RAG pipeline silently degrades to near-uselessness rather than
erroring, which is its own kind of "costs the request".

**Better-justified minimal alternative** (offered because I can justify it, per
the brief): compute `conservative_model_limit()` from `MODEL_LIMITS` alone
(`min` = 8191, from `'gpt-4'`), and keep the live catalog for exact-id
resolution only. `MODEL_LIMITS` is documented as chat-model context windows;
the live catalog is deliberately content-based and therefore mixes embedding and
2B-vision windows. This preserves "err low" (8191 is far below every mainstream
model), needs no `classType` filtering — which the lead rightly avoided — and is
a one-line change. Clamping instead (`max(min(known), FLOOR)`) is worse: the
floor constant is 8192 while three real chat nodes publish 8191
(`llm_bedrock:113`, `llm_deepseek:210`, `llm_kimi:111`), so it would budget one
token above a real window.

Whichever the lead picks, **the README's stated number must match the shipped
behaviour** — see (h).

## (d) Unrelated changes — ACCEPT

Fix commit `8f820ae91` touches exactly three files: `optimizer.py`,
`README.md`, `test/context_optimizer/test_all.py`. Hunk-by-hunk (`git diff -U0
... | grep '^@@'`), every `optimizer.py` hunk falls between lines 36 and 374 —
imports, class docstring, removal of `_CATALOG_ROOT`/`_CATALOG_GLOB`/
`_catalog_cache`, the `__init__` catalog snapshot, and the catalog/resolve
methods. Nothing at or below line 376 (`_parse_pct`, encoding resolution, token
counting, truncation, summarisation, ranking, `optimize`) is touched.

Merge commit `9b4cfcce` is clean: 561 develop-side changed files vs 561 brought
onto the PR, `comm -23` and `comm -13` both empty, no conflict markers.

## (e) Test quality — MIXED

- **They do drive the production path.** `test_all.py:234-235` monkeypatches
  `rocketlib.getServiceDefinitions` / `getServiceDefinition` on the real module,
  so `_engine_model_definitions` runs unmodified. Not bypassed. ACCEPT.
- **`test_no_filesystem_access_during_discovery` (`test_all.py:900-909`) would
  catch a regression to globbing** — it raises from `Path.glob` and `Path.rglob`
  and still requires a populated catalog. ACCEPT.
- **But no test uses the real return shape.** `_llm_definitions`
  (`test_all.py:238-246`) builds `index[name] = {'classType': ['llm']}`, a flat
  dict; `test_unusable_registry_index_yields_empty_catalog` parametrises over
  `[None, 'not-a-dict', [], 42]` and never over the envelope. The 165-test suite
  is green against a contract the engine does not implement. REQUIRED: a test
  feeding `{'services': {...}, 'version': N}`.

## (f) Suite re-run — matches the lead exactly

`165 passed, 1 skipped` (skip: "the tiktoken stub splits on whitespace, so no
two encodings can disagree"). Same shim approach as specified. ACCEPT.

## (g) Before/after probe — confirms the reviewer's diagnosis

```
BEFORE (9b4cfcce, _CATALOG_ROOT -> empty dir): catalog=0  unknown-model budget = 128000
AFTER  (8f820ae9, registry empty)            : catalog=0  unknown-model budget = 8191
   smallest window in MODEL_LIMITS = 8191
```

The optimistic-128 000 removal is real and the direction is right. But 8191 is
reached through `MODEL_LIMITS`, not through the catalog the PR claims to read —
which is the (a) blocker restated.

## (h) README / services.json — NEEDS-CHANGE

- `nodes/src/nodes/context_optimizer/services.json` — untouched by the fix
  commit. ACCEPT.
- The `ROCKETRIDE:GENERATED:PARAMS` block spans `README.md:61-83`; both changed
  lines are at `:26` and `:31`, outside it. **Untouched.** ACCEPT.
- `README.md:31` states the conservative fallback is "on develop today that is
  2 048 tokens". Shipped behaviour is **8191**. Once (a) is fixed it becomes
  2048 — for the reason given in (c), which the sentence does not convey.
  NEEDS-CHANGE either way.
- `README.md:26` describes discovery as "`rocketlib.getServiceDefinitions()` to
  enumerate the registered types" — accurate only after the envelope fix.

## (i) Surviving invariants — ACCEPT

- NaN: explicitly handled at `optimizer.py:385-389` (`if pct != pct`), ahead of
  the range clamps, with its own warning.
- Token accounting: `_load_model_catalog` reads `profile.get('modelTotalTokens')`
  at `:309`, not `modelOutputTokens`; `_record` at `:297-298` keeps the smaller
  window on conflict.
- `pytest -k "nan or percent or pct or multi or question or token or smaller"`
  → 30 passed, 1 skipped.

## PR #1489 — REQUIRED corrections

1. **Unwrap the envelope in `nodes/src/nodes/context_optimizer/optimizer.py:258-262`.**
   `rocketlib.getServiceDefinitions()` returns `{"services": {...}, "version": N}`
   (`services.cpp:2153-2155`), not a flat index. Mirror the repo's existing
   consumer at `packages/ai/src/ai/modules/task/services_catalog.py:145-146`:

   ```python
   raw = rocketlib.getServiceDefinitions()
   if not isinstance(raw, dict):
       return {}
   index = raw.get('services') or {}
   if not isinstance(index, dict):
       return {}
   ```

   Without this the node's entire registry-based discovery is dead code.
2. **Fix the docstring at `optimizer.py:233-234`** — the index is not "keyed by
   logical type"; it is an envelope whose `services` member is. Add the
   `INTERNAL`-capability and `--serviceCategory`/`--serviceName` caveats
   (`services.cpp:2090`, `:2093-2094`, `:2099-2101`).
3. **Add a test that feeds the real shape.** At minimum one case asserting a
   populated catalog from `{'services': {<lt>: {...}}, 'version': N}`, plus the
   envelope in the `test_unusable_registry_index_yields_empty_catalog`
   parametrisation. Without it the suite stays green against a contract the
   engine does not implement.
4. **Decide the conservative fallback deliberately**, knowing it silently moves
   from 8191 to 2048 the moment correction 1 lands, and that 2048 is an
   *embedding* model's input limit
   (`nodes/src/nodes/embedding_openai/services.json:108,116`). My
   recommendation is in (c): source `conservative_model_limit()` from
   `MODEL_LIMITS` only.
5. **Correct `README.md:31`** to state the number the code actually produces,
   and name its source honestly.

## PR #1489 — OPTIONAL suggestions

- Note in the `_engine_model_definitions` docstring that the server caches this
  same call once per process (`services_catalog.py:26-30`) and that the node
  deliberately does not — 8 ms per pipeline start, measured.
- `rocketlib/__init__.pyi:825-831` documents `getServiceDefinitions` as
  returning "all registered service definitions", and `engine.py:294-298`
  duplicates the singular docstring. Both are misleading and neither declares
  the `None` return the bindings can produce. A drive-by docstring fix in
  rocketlib would stop the next caller making the same mistake — but it belongs
  in its own PR, not this one.

---

## Reproduction

Sub-worktrees (created by this verifier, safe to remove):

```
.claude/worktrees/agent-a007c49ad51eaf9e4/wt/c683      -> 64571f500
.claude/worktrees/agent-a007c49ad51eaf9e4/wt/c683pre   -> e1f06b4f  (fails-before)
.claude/worktrees/agent-a007c49ad51eaf9e4/wt/c1489     -> 8f820ae91
```

Test environment: python 3.12 venv with `pydantic json5 pytest pytest-asyncio`;
`sitecustomize.py` on `PYTHONPATH` setting `sys.modules['engLib'] = MagicMock()`,
a no-op `depends` module exposing `depends()`, and
`packages/server/engine-lib/rocketlib-python/lib`, `packages/ai/src`,
`packages/client-python/src` on `sys.path`.

Probe scripts used for the envelope, before/after, shim-identity and cost
findings live under the verifier scratchpad and are reproducible from the
commands quoted inline above.
