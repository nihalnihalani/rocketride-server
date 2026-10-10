# TASK 3 — research for the #1489 fix (services*.json catalogue discovery)

All line refs are against **develop @ f9a25cbbd73f8feb9fbc99ea3aeb5bd241dafc1e** unless a PR ref is
named. Verified by reading source directly (`git show <rev>:<path>`), not inferred.

## 1. The bug being researched, precisely

`nodes/src/nodes/context_optimizer/optimizer.py` (PR #1489 head `a61e8483`, lines 138-140, 269-327):

```python
_CATALOG_ROOT: ClassVar[Path] = Path(__file__).resolve().parent.parent   # line 138
_CATALOG_GLOB: ClassVar[str] = 'llm_*/services*.json'                    # line 139
_catalog_cache: ClassVar[Optional[Dict[str, int]]] = None                # line 140
...
@classmethod
def _load_model_catalog(cls) -> Dict[str, int]:            # line 269
    ...
    paths = sorted(cls._CATALOG_ROOT.glob(cls._CATALOG_GLOB))  # line 293
    ...                                                          # hand-rolled JSONC
    service = json.loads(cls._strip_jsonc(path.read_text()))     # stripper (line ~230)
```

`_CATALOG_ROOT` is computed from `__file__`, i.e. "two directories up from wherever this
particular .py file physically sits." That is only `nodes/src/nodes/` (with `llm_*` as true
siblings) when the node is running **out of this repo's own source tree**. This is what the
still-open, unresolved thread `dsapandora`/`discussion_r3950836282` (PR #1489, thread #13,
`optimizer.py:293`, current at head) flags.

## 2. How `--node_path` materialization actually lays nodes out — confirms the bug is structural, not an edge case

C++ side, `packages/server/engine-lib/engLib/store/services/services.cpp` (~line 1990-2013),
the function that discovers/loads every node's `services*.json` at engine startup:

```cpp
auto rootPath = application::projectDir() ? application::projectDir() / "nodes/src/nodes" : "";
if (!rootPath || !file::exists(rootPath) || !file::isDir(rootPath))
    rootPath = application::execDir() / "nodes";              // packaged/prod mode
...
if (auto ccode = loadServices(rootPath, (Text) "*")) return ccode;   // built-in nodes

// Also scan a `local_nodes` folder under --node_path=<dir>, if given.
if (NodePath) {
    auto localRoot = _cast<file::Path>(*NodePath) / "local_nodes";
    if (file::exists(localRoot) && file::isDir(localRoot)) {
        LOG(Services, "Loading workspace-local nodes from", localRoot);
        if (auto ccode = loadServices(localRoot, (Text) "*")) return ccode;   // user's local nodes
    }
}
```

Same story on the Python-interpreter side, `packages/server/engine-lib/engLib/python/init.cpp`
(~line 45, 160-172) — `--node_path=<dir>` only ever contributes `<dir>` to `sys.path` (so nodes
import as `local_nodes.<node>`) **when `<dir>/local_nodes/` exists**; the CLI help text in
`packages/server/engine-core/apLib/application/init.cpp:30` confirms: *"--node_path=&lt;dir&gt;
Directory containing a 'local_nodes' folder of..."*.

**Conclusion:** built-in nodes (including every `llm_*`) and `--node_path`-materialized nodes are
two structurally separate roots, loaded by two separate `loadServices()` calls into the *same*
merged in-memory registry — a `local_nodes/` workspace is not, and is never intended to be, a
mirror of `nodes/src/nodes/`. A node whose own file happens to live under
`<node_path>/local_nodes/context_optimizer/` has `_CATALOG_ROOT` resolve to
`<node_path>/local_nodes/`, which by construction never contains `llm_*` — the glob returns zero
matches every time in that layout, not just when something is "missing." This corroborates
dsapandora's read exactly.

## 3. The supported, engine-native way to read the catalogue — this is the fix

`rocketlib` (the Python-visible module every node already runs inside) exposes two functions
that are direct bindings onto the compiled engine, **not** a re-implementation:

`packages/server/engine-lib/rocketlib-python/lib/rocketlib/__init__.pyi:825,829` (type stubs):
```python
def getServiceDefinition(logicalType: str) -> Dict[str, Any]: ...
def getServiceDefinitions() -> Dict[str, Any]: ...
```

`packages/server/engine-lib/rocketlib-python/lib/rocketlib/engine.py:284-297` (implementation —
literally a passthrough to the C++ engine, no filesystem access of its own):
```python
def getServiceDefinition(logicalType: str) -> Dict:
    """Return a service definition given a logical name."""
    ...
getServiceDefinition = engLib.getServiceDefinition  # noqa

def getServiceDefinitions() -> Dict:
    """Return a service definition given a logical name."""   # (docstring is copy-pasted, sic)
    ...
getServiceDefinitions = engLib.getServiceDefinitions  # noqa
```

`getServiceDefinitions()` returns **every** service the engine registered from *both* roots above
(built-in `nodes/src/nodes/**` **and** `--node_path`'s `local_nodes/**`), already JSON-parsed by
the engine's own loader — so switching to it also removes `optimizer.py`'s hand-rolled
`_strip_jsonc()` comment/trailing-comma stripper (~40 lines), exactly as dsapandora's comment
predicted ("would also drop the local JSONC parser").

**This repo already has the reference usage pattern** — `packages/ai/src/ai/common/config.py:84,251`
and `packages/ai/src/ai/modules/task/services_catalog.py:145` both call
`getServiceDefinition(logicalType)` / `getServiceDefinitions()` from `rocketlib` for exactly this
purpose (resolving a node's own config schema / building the services catalog for the UI). No new
API needs to be invented; `context_optimizer` would be the first *node instance* (as opposed to
engine-module) caller, but the call is already idiomatic in this codebase.

**Recommended fix shape** (for the lead, not applied here — this agent is read-only): replace
`_load_model_catalog()`'s `cls._CATALOG_ROOT.glob(...)` + `_strip_jsonc` + `json.loads` block with
one call to `rocketlib.getServiceDefinitions()`, then walk `service.get('preconfig', {}).get('profiles',
{})` per returned entry exactly as the existing loop already does (the `preconfig.profiles[*].model`
/ `modelTotalTokens` walk at optimizer.py lines ~294-320 does not need to change — only how `service`
dicts are obtained does). Filter to services whose name matches `llm_*` if only LLM profiles should
count (the current glob effectively does this via `llm_*/services*.json`); `getServiceDefinitions()`
returns all node kinds, so the same `llm_*` name filter should move into Python
(`if not name.startswith('llm_'): continue`) rather than being implicit in a glob pattern.

## 4. Does context_optimizer still need its own cache after switching?

`_catalog_cache: ClassVar[Optional[Dict[str, int]]] = None` (line 140) — populated once by
`model_catalog()` (line 331-334) and never invalidated; dsapandora's comment calls this out too
("the class-level cache, which a later `sync_models` never invalidates").

The engine has its **own** higher-level cache for this exact data, but it is not something a node
should reach for: `packages/ai/src/ai/modules/task/services_catalog.py` (module docstring, lines
23-54) wraps `getServiceDefinitions()` in a build-once `_catalog` cache **for the server-side
`rrext_services` bulk API/UI surface** (canvas node palette), with an explicit
`invalidate()` called by the engine "whenever those change (node install / update / removal)"
(docstring, "Invalidation" section). That cache is one layer above raw `rocketlib` and lives in a
different process role (the services API, not a running pipeline node) — `context_optimizer`
should not import it.

Practically: `getServiceDefinitions()` itself is a direct read of the engine's already-in-memory
registry (no file I/O, no JSON parse on the node's side), so **if `context_optimizer` calls it
directly instead of caching a class-level snapshot, the staleness problem dsapandora raised
disappears on its own** — every `optimize()` call would see the engine's current registry, which is
exactly as fresh as the engine's own node installs. Whether to still memoize per-process for
speed is a minor call the lead can make (the C++ call is registry-lookup cheap, not a network or
disk-scan cost, so the original perf motivation for `_catalog_cache` mostly goes away too).

## 5. `modelTotalTokens` — exact declaration shape confirmed in a real `llm_*` file

`nodes/src/nodes/llm_openai/services.json` (JSONC — comments/trailing commas, which is why the
node's own `_strip_jsonc` exists at all), at `preconfig.profiles.<key>.modelTotalTokens`, e.g.:

```jsonc
"modelTotalTokens": 16384,
"modelTotalTokens": 1050000, // openrouter
"modelTotalTokens": 400000, // openrouter
"modelTotalTokens": 128000, // manual
```

Every profile also carries a sibling `modelOutputTokens` key (see #2151 below) — `optimizer.py`
correctly reads only `modelTotalTokens`, per dsapandora's review ("The token accounting is right
where it matters — `modelTotalTokens` rather than the output limit").

## 6. What #2151 fixed (referenced in the review as "the same failure class, reached another way")

**#2151 is a closed GitHub *issue*, not a PR** (`gh issue view 2151`): *"fix(sync_models): 38
profiles send the context window as max_tokens, ~70 more silently truncate at 4096"*, opened
2026-08-31, closed 2026-09-01. Two catalogue-data defects it documented, both caused by
`tools/sync_models` (the script that regenerates `llm_*/services*.json` profile data from
provider APIs via litellm), **not** by engine or node logic:

1. `modelOutputTokens == modelTotalTokens` for 38 profiles across 7 nodes (`llm_mistral` 16,
   `llm_openai` 7, `llm_xai` 7, `llm_deepseek` 4, `llm_qwen` 2, `llm_kimi` 1, `llm_minimax` 1) —
   the full context window gets sent as `max_tokens`, which the provider rejects outright. Root
   cause documented inline in `tools/sync_models/src/sync_models.config.json`: *"litellm swaps
   max_output_tokens with the context window"* for some providers.
2. ~70 profiles have **no** `modelOutputTokens` at all, so
   `packages/ai/src/ai/common/chat.py:100` (`self._modelOutputTokens = config.get('modelOutputTokens',
   4096)`) silently caps generation at 4096 tokens with no signal to the caller — worst on the
   vision nodes (scanned-document output tends to be long).

**Why dsapandora cites it**: not because the fix is reusable code, but as *precedent in this exact
codebase* that "erring high costs the request" (a provider-rejected call) is a real, previously
diagnosed failure mode from bad/missing catalogue numbers — reinforcing the ask that
`context_optimizer`'s own fallback-on-empty-catalog direction should be conservative (bias the
default limit low) rather than optimistic (today: `DEFAULT_MODEL_LIMIT = 128000`, which
over-budgets any real model with a smaller window, e.g. a 32k model gets 4x its actual window and
the provider call fails).

## Answer to "which API to use" (one line)

Call `rocketlib.getServiceDefinitions() -> Dict[str, Any]` (already imported this way elsewhere in
the codebase, e.g. `packages/ai/src/ai/modules/task/services_catalog.py:67,145`) instead of
globbing `Path(__file__).resolve().parent.parent.glob('llm_*/services*.json')`; keep the existing
`preconfig.profiles[*].model` / `modelTotalTokens` extraction loop, add an `llm_*` name filter in
Python, and drop `_strip_jsonc` since the engine hands back already-parsed dicts.
