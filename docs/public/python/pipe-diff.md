---
title: Pipeline Diff
sidebar_position: 14
---

# Pipeline Diff (`rocketride diff`)

A raw `git diff` of a `.pipe` file is dominated by **canvas coordinate churn**:
nudge a node and its `ui.position` `x`/`y` move, pan or zoom and the top-level
`viewport` shifts. None of that changes behavior, yet it buries the lines that do
— a swapped LLM provider, a re-tuned chunk size, a rewired retrieval step.

`rocketride diff` computes a **semantic** diff instead. It groups changes into
**Nodes** (added / removed / re-provisioned), **Edges** (the wiring between
components) and **Config** (per-field changes as readable dotted paths), and
collapses all layout churn into a single `Layout: changed` line.

It ships with the Python client as the `rocketride diff` CLI command, and the same
engine is importable as the `rocketride.pipediff` package.

> **Local only — no engine, no auth, no network.** Unlike every other
> subcommand, `diff` reads files (or a git ref) and compares parsed JSON entirely
> on your machine. It therefore takes **none** of the `--uri` / `--apikey` /
> `--token` connection options the other commands share. Python CLI only.

- [Install](#install)
- [Quickstart](#quickstart)
- [CLI reference](#cli-reference)
- [What counts as a change](#what-counts-as-a-change)
- [Output modes](#output-modes)
- [Review pipelines like code in CI](#review-pipelines-like-code-in-ci)
- [Python API](#python-api)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)

---

## Install

`diff` needs no extra: it is part of the `rocketride` CLI and adds no runtime
dependencies.

```bash
pip install rocketride
```

> **Before the CLI release:** `rocketride diff` is not in a PyPI release yet —
> 1.4.0 and earlier do not include it; the first release with it will be 1.5.0
> or later. Until then install the client package from this
> repository at a pinned commit — pip executes the source's build code, so pin a
> full commit SHA rather than a branch:
>
> ```bash
> pip install "rocketride @ git+https://github.com/rocketride-org/rocketride-server@<full-commit-sha>#subdirectory=packages/client-python"
> ```

## Quickstart

```bash
# Compare two files on disk (old first, then new)
rocketride diff old.pipe new.pipe

# Compare a working-tree file against a git ref (runs `git show <ref>:<file>`)
rocketride diff --git HEAD rag.pipe
rocketride diff --git main rag.pipe

# Machine-readable output
rocketride diff old.pipe new.pipe --json
rocketride diff old.pipe new.pipe --markdown

# Include the layout churn that is hidden by default
rocketride diff old.pipe new.pipe --include-layout
```

Because the command exits `1` when it finds a semantic change, it drops straight
into a shell gate:

```bash
if ! rocketride diff --git "origin/main" rag.pipe; then
  echo 'pipeline behavior changed — review the diff above'
fi
```

## CLI reference

```bash
rocketride diff <old.pipe> <new.pipe> [--include-layout] [--json | --markdown] [--exit-zero]
rocketride diff --git <ref> <file.pipe> [--include-layout] [--json | --markdown] [--exit-zero]
```

| Flag | Description |
| --- | --- |
| `<old.pipe> <new.pipe>` | The two files to compare (positional, old first). Pass exactly one file with `--git` instead. |
| `--git <ref>` | Diff the working-tree `FILE` against `<ref>` via `git show <ref>:<FILE>`, looking the file up under the path given. `<ref>` is any revision git accepts — a commit SHA, branch, tag, `HEAD`, `HEAD~1`, `origin/main` — and must not be empty. If the file does not exist in `<ref>`, everything is reported as added, plus a version change from `null` when the file has a `version`, and `layout changed` when its `viewport` is non-empty. A symlink committed as a symlink is compared through its target; on a case-insensitive filesystem, a differently cased spelling of a tracked file is compared against that file. |
| `--include-layout` | Enumerate the layout churn that is hidden by default — each node's `ui` block as `ui.*` changes on that node, and the top-level `viewport` as `viewport.*` changes — and count it, so a layout-only edit then exits `1`. |
| `--json` | Emit a single JSON document to stdout (mutually exclusive with `--markdown`). |
| `--markdown` | Emit compact, PR-comment-friendly Markdown to stdout (mutually exclusive with `--json`). |
| `--exit-zero` | Always exit `0` on a successful run, even when changes are found. Use for informational, non-gating runs. |

**Exit codes:** `0` no semantic changes (or any successful run with
`--exit-zero`); `1` semantic changes were found; `2` usage error, or an
unreadable / unparseable file, or a bad git ref. Errors always go to stderr, so
`--json` and `--markdown` output on stdout stays pure.

Non-JSON constants (`NaN`, `Infinity`, `-Infinity`), numeric overflow, and
nonzero values that underflow to zero are rejected with exit `2`. Fractional
and exponent literals use finite IEEE 754 binary64 precision: literals such as
`0.1` and `0.10000000000000001` round to the same value and compare equal.
Integer literals retain exact Python integer precision, subject to the JSON
decoder's size limit. The same rules apply to files read from Git; an
already-parsed `dict` must also contain only finite floats. Excessive nesting
that exceeds the parser, comparison, or renderer limit produces an actionable
error on stderr with exit `2` and no report on stdout. `--exit-zero` does not
suppress these errors.

`--json` here is a **format flag** — a whole JSON document on stdout — not the
shared `--json [FILE]` result envelope the connected subcommands use. That
difference is deliberate: `diff` produces a report, not a command result.

## What counts as a change

- **Nodes** are matched by `id`. A new or deleted `id` is an add/remove; an `id`
  present on both sides with a different `provider` is a provider change
  (compared type-sensitively, like config). A duplicate `id` within one file is
  rejected with exit `2` rather than silently shadowing a node.
- **Config** is deep-diffed into dotted paths — nested objects become
  `config.default.strlen`, list items become `config.instructions[0]` — and each
  leaf is reported as added, removed, or changed with its old → new value. JSON
  types are compared type-sensitively, so `false` → `0` is a change.
- **Edges** are the directed wires between components, reconstructed from every
  component's `input[]` (data lanes) and `control[]` (agent orchestration lanes,
  such as an agent's `llm`, `tool`, or `memory`). Rewiring a step shows up as a
  removed edge plus an added edge.
- **Version** — the top-level `version` field — is always reported and always
  counts as a change; it is never hidden by the layout rules.
- **Layout** — each node's `ui` block and the top-level `viewport` — is ignored by
  default and summarized as a single `Layout: changed` line, so a pure canvas move
  exits `0`. `--include-layout` enumerates the individual `ui.*` and `viewport.*`
  fields and makes them count, so a canvas-only edit then exits `1`.
- **Canvas groups.** The editor saves a group's children inside the group
  component, under `config.pipeline.components`. Each child is diffed as a node
  in its own right, matched by `id` like any other: its `ui` is layout, its
  wiring is edges, and its provider and config changes are reported on the child.
  Moving a node into or out of a group changes only its `ui` (`parentId` and a
  group-relative position), so it is layout too. Ids must be unique across
  groups.
- **Everything else at the top level is ignored.** `diff` reads exactly
  `components`, `version` and `viewport`; `project_id`, `isLocked`, and any key a
  later schema adds are editor/session metadata rather than pipeline behavior, so
  editing one never reports a change (even under `--include-layout`).

## Output modes

The default **human** output is grouped and colored (color auto-disables when
piped or when `NO_COLOR` is set), with `+` added, `-` removed, `~` changed.
Control characters in values — C0, C1, and the Unicode bidi and line-separator
controls — are printed as `\xNN`/`\uNNNN` escapes:

```text
Pipeline diff: 1 node changed, layout changed

Config
  chunker_1
    ~ config.default.strlen: 512 -> 1024

Layout: changed (ui/viewport)
```

`--json` emits one stable document with sorted keys — `edges`, `nodes`, a
`summary` block with counts and the overall `has_semantic_changes` flag, and
`viewport`:

```json
{
  "edges": { "added": [], "removed": [] },
  "nodes": {
    "added": [],
    "changed": [
      {
        "config_changes": [
          { "kind": "changed", "new": 1024, "old": 512, "path": "config.default.strlen" }
        ],
        "id": "chunker_1",
        "provider_change": null
      }
    ],
    "removed": []
  },
  "summary": {
    "config_changes": 1,
    "edges_added": 0,
    "edges_removed": 0,
    "has_semantic_changes": true,
    "layout_changed": true,
    "nodes_added": 0,
    "nodes_changed": 1,
    "nodes_removed": 0,
    "provider_changes": 0,
    "version_change": null,
    "viewport_changes": 0
  },
  "viewport": []
}
```

The top-level `viewport` array carries the same `{"path", "kind", "old", "new"}`
shape as a config change and is populated only under `--include-layout`;
`summary.viewport_changes` is its length.

`--markdown` emits a compact, PR-comment-friendly report — a one-line summary,
bullet lists for nodes and edges, and a table for config changes:

```markdown
**Pipeline diff:** 1 node changed, layout changed

**Config**

| Node | Field | Change |
| --- | --- | --- |
| `chunker_1` | `config.default.strlen` | `512` → `1024` |

_Layout (ui/viewport) changed._
```

Values reaching the Markdown report are untrusted `.pipe` content, so every value
is wrapped in a code span whose fence is longer than any backtick run inside it,
and pipes are escaped so a value cannot split the table row or break out of the
comment. Node and edge add/remove signs are also code-spanned, preserving the
visible `+` or `-` beside each identity after GitHub renders the list.

In every format but JSON, strings print bare and other values use JSON spelling
(`true`, `null`, `{"k": "v"}`). An empty string prints as `""`, and when a change
crosses types (`512` → `"512"`) strings are JSON-quoted so the two sides never
look alike.

## Review pipelines like code in CI

The supported way to wire this into pull requests is the bundled
[`pipe-diff` composite action](https://github.com/rocketride-org/rocketride-server/tree/develop/.github/actions/pipe-diff),
which finds every changed `.pipe`, diffs each against the merge base with the
pull request's base branch, and maintains one **sticky** comment:

```yaml
# .github/workflows/pipe-diff.yml
name: Pipeline diff
on: pull_request
permissions:
  contents: read
  pull-requests: write
jobs:
  diff:
    runs-on: ubuntu-latest
    steps:
      # default fetch-depth: 1 is fine; the action fetches the base itself
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4
      - uses: rocketride-org/rocketride-server/.github/actions/pipe-diff@develop
```

Pin `@develop` to a commit SHA once the action is released, exactly as
`actions/checkout` is pinned above.

The [CLI reference](/connect/cli#diff) covers the action's inputs, the fork
pull-request caveat (a fork's `GITHUB_TOKEN` is read-only, so the action warns
and falls back to the job summary), and the inline equivalent for teams that
would rather not vendor a composite action.

## Python API

The CLI is a thin shell over `rocketride.pipediff`, which is importable and has
the same no-network guarantee. Every name below is exported from the package
root.

```python
from rocketride.pipediff import diff_pipes, load_pipe, render_markdown

old = load_pipe('old.pipe')
new = load_pipe('new.pipe')
diff = diff_pipes(old, new)

if diff.has_semantic_changes:
    print(render_markdown(diff, title='rag.pipe'))
```

### Engine

| Function | Description |
| --- | --- |
| `load_pipe(path_or_obj)` | Load and validate a pipeline from a filesystem path or an already-parsed `dict`. Raises `PipeDiffError` for an unreadable file, invalid UTF-8, invalid JSON, a non-object top level, a missing or non-list `components`, a component without a non-empty string `id`, a duplicate component `id`, or malformed `input[]` / `control[]` wiring. |
| `diff_pipes(old, new, *, include_layout=False)` | Compare two loaded pipelines and return a `PipeDiff`. `include_layout` folds each node's `ui` differences into its field changes and enumerates the top-level `viewport` into `PipeDiff.viewport_changes`. |
| `deep_diff_config(old, new)` | Deep-diff two config dicts into a list of `FieldChange` with dotted paths (`None` is treated as an empty dict). The building block `diff_pipes` uses per node. |
| `resolve_git_ref(ref, file_path)` | Return the parsed pipeline at a git ref via `git show <ref>:<path>`, or `None` when the file does not exist in that ref. Raises `PipeDiffError` when the path is outside a repository, the ref is unknown, `git` is unavailable or times out, or the retrieved contents are not a valid pipeline. Arguments are passed as an argv list (never a shell string). |
| `PipeDiffError` | The single exception type the package raises. The CLI maps it to exit code `2`. |

### Data model

| Type | Description |
| --- | --- |
| `PipeDiff` | The whole diff: `node_changes`, `edge_changes`, `version_change` (an `(old, new)` tuple or `None`), `layout_changed`, `viewport_changes`, and the `has_semantic_changes` property that decides the exit code. |
| `NodeChange` | One component change: `id`, `kind` (`added` / `removed` / `provider` / `config`), `provider_old`, `provider_new`, `field_changes`. A node whose provider *and* config changed yields two entries. |
| `FieldChange` | One field-level change: `path` (e.g. `config.default.strlen`, `ui.position.x`), `kind` (`added` / `removed` / `changed`), `old`, `new`. |
| `EdgeChange` | One wire: `from_id`, `lane` (the data `lane`, or the control `classType` such as `llm` / `tool` / `memory`), `to_id`, `kind` (`added` / `removed`). |

### Reporters

| Function | Description |
| --- | --- |
| `render_human(diff, *, use_color)` | The grouped terminal report. `use_color` is explicit — the CLI decides it from `NO_COLOR` and `stdout.isatty()`. |
| `render_json(diff)` | A plain `dict` ready for `json.dumps(..., sort_keys=True)`: `nodes`, `edges`, `viewport`, `summary`. |
| `render_markdown(diff, *, title=None)` | The PR-comment report. `title` adds a heading above it; without one the output starts at the `**Pipeline diff:**` summary line. |

Reporters take a `PipeDiff` and return a string (or `dict`) — they print
nothing, so they compose into your own tooling.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `invalid choice: 'diff'` | The installed `rocketride` predates the subcommand — install from the repository at a pinned commit (see [Install](#install)). |
| Exits `2` with "Unknown git ref" | `--git` was given a ref this repository does not have. Fetch it first — in CI, check out with enough history (`fetch-depth: 0`) or fetch the base branch explicitly. |
| Exits `2` with "duplicate component id" | Two components in one file share an `id`. That would silently hide every change to the shadowed node, so it is rejected rather than diffed. |
| A canvas-only edit exits `0` and prints `Layout: changed` | Working as designed. Pass `--include-layout` to enumerate and count it. |
| Exit code `1` breaks the build | `1` means "changes found", not "failure". Add `--exit-zero` for an informational run. |

## Limitations

- **Nodes are matched by `id` only.** Delete a node and add an equivalent one
  under a new `id` and the diff reports a removal plus an addition, not a rename.
- **`--git` needs a real repository.** The ref side is read through `git show`, so
  the file must live inside a git worktree and the ref must be present locally.
- **No engine validation.** `diff` checks that both files are well-formed
  pipelines, not that they are runnable — use [`rocketride
  validate`](/connect/cli#validate) for that.

## See also

- [CLI reference](/connect/cli#diff) — the `diff` flag table alongside the rest of
  the CLI, and the full CI recipe
- [Side-by-side example](https://github.com/rocketride-org/rocketride-server/blob/develop/examples/pipe-diff-example.md)
  — the full before/after contrast and the PR-comment output
- [Pipeline reference](/reference/pipeline-reference) — the `.pipe` schema this
  command reads
- [Python SDK](/clients/python) — the client the command ships with
