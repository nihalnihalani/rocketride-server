# RocketRide Pipe Diff action

A composite GitHub Action that posts a **semantic** diff of changed `.pipe`
pipeline files as a single, sticky pull-request comment.

Raw JSON diffs of `.pipe` files are dominated by canvas coordinate churn — the
per-node `ui` block and the top-level `viewport` — which buries the changes that
actually matter. This action wraps the local [`rocketride diff`](../../../packages/client-python)
CLI subcommand to surface only what changed: nodes added/removed, provider
changes, config field changes, and edge (wiring) additions/removals.

The action runs **entirely on the runner**. Like the `rocketride diff` command it
wraps, it never contacts the RocketRide engine or the network — it only reads
files and git objects and compares parsed JSON. It therefore needs no
`--uri`/`--apikey`/`--token` credentials of any kind.

## Usage

Add a workflow that checks out the repo and runs this action on pull requests:

```yaml
name: Pipe diff
on:
  pull_request:

# Reading the repo, and writing the sticky comment.
permissions:
  contents: read
  pull-requests: write

jobs:
  pipe-diff:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4
      - uses: ./.github/actions/pipe-diff
```

`actions/checkout` with its default `fetch-depth: 1` is enough — the action
fetches the PR base commit itself before diffing.

### With inputs

```yaml
      - uses: ./.github/actions/pipe-diff
        with:
          files: 'pipelines/**/*.pipe'   # restrict which .pipe files are considered
          python-version: '3.12'
          cli-version: '==1.4.0'          # pin a specific published rocketride release
          comment: 'true'                 # set 'false' to skip commenting
          include-layout: 'false'         # set 'true' to also report ui/viewport churn
```

## Inputs

| Input            | Default       | Description |
| ---------------- | ------------- | ----------- |
| `files`          | `**/*.pipe`   | Git pathspec glob selecting the `.pipe` files to consider. Git's `:(glob)` magic is applied automatically, so `**` matches across directories. Only files that actually changed versus the PR base are diffed. |
| `python-version` | `3.12`        | Python version passed to `actions/setup-python`. RocketRide requires Python >= 3.10. |
| `cli-version`    | `` (empty)    | pip version specifier appended to the `rocketride` requirement, e.g. `==1.4.0` or `>=1.4,<2`. Empty installs the latest published release. The run **fails fast** with a clear message if the installed CLI lacks the `diff` subcommand. |
| `comment`        | `true`        | When `true`, post or update one sticky PR comment. Set to `false` to compute the diff (job log + outputs) without commenting; that mode needs no `pull-requests: write` permission. |
| `include-layout` | `false`       | When `true`, treat canvas layout churn (per-node `ui` blocks and the top-level `viewport`) as meaningful and enumerate it. When `false` (default) a pure-layout change is reported as `no semantic changes (layout only)`. |

## Outputs

| Output                 | Description |
| ---------------------- | ----------- |
| `changed-files`        | Number of changed `.pipe` files considered (added or modified vs the PR base). |
| `has-semantic-changes` | `true` when at least one changed `.pipe` file has semantic changes, else `false`. |
| `comment-body-file`    | Path to the generated Markdown comment body (useful for debugging or reuse). |

## Permissions

The sticky-comment step needs `pull-requests: write` (comments are issue
comments on the PR). `contents: read` is required to check out and diff the
repository. If you set `comment: false`, only `contents: read` is needed.

The action authenticates the GitHub REST calls with the workflow's built-in
`GITHUB_TOKEN`; it never prints the token.

## Behavior

- **Sticky comment.** The action maintains exactly one comment per PR, found and
  updated via a hidden HTML marker (`<!-- rocketride-pipe-diff -->`). Re-runs
  update that comment in place instead of stacking new ones.
- **Layout noise is hidden by default.** A change that only moves nodes on the
  canvas produces exit code 0 from the CLI and is summarized as
  `No semantic changes (layout only).`. Pass `include-layout: true` to enumerate
  the `ui`/`viewport` deltas instead.
- **Version changes are always reported** (they are semantic-ish), regardless of
  `include-layout`.
- **New files.** A `.pipe` file added in the PR (absent in the base) is diffed
  against an empty pipeline, so every node and edge shows up as added.
- **Deleted files.** Removed `.pipe` files are noted in the comment (there is no
  working-tree file to diff).
- **Failure semantics.** The action does **not** fail merely because semantic
  changes exist — it is informational. It **does** fail (and emits an `error`
  annotation) when a changed `.pipe` file cannot be parsed or diffed, so a broken
  pipeline in a PR is surfaced as a red check.

## Local equivalent

Everything the action does per file is one local CLI call — no server, no token:

```bash
# Diff a working-tree .pipe file against the PR base commit, as Markdown:
rocketride diff --git "$(git merge-base origin/main HEAD)" pipelines/my.pipe --markdown

# Or diff two files directly:
rocketride diff old.pipe new.pipe

# Add --include-layout to surface ui/viewport churn; --json for machine output.
```

Exit codes match the action's per-file logic: `0` = no semantic changes,
`1` = semantic changes, `2` = usage error / unreadable / unparseable file.

## Pinned dependencies

Third-party actions are pinned by full commit SHA (with a version comment),
matching the convention in [`.github/workflows`](../../workflows):

- `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065` (v5)
- `actions/github-script@60a0d83039c74a4aee543508d2ffcb1c3799cdea` (v7)

## License

MIT — see the repository [`LICENSE`](../../../LICENSE).
