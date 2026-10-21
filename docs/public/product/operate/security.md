---
title: Security
---

# Security

An overview of how RocketRide handles credentials, network exposure, and
authentication across its components.

## Credential isolation

API keys are configured **per node** inside the pipeline definition. Each node
holds only its own credentials — there are no shared global secrets, no
credential store, and no key that grants access to more than one provider.

```json
{
  "id": "llm_1",
  "provider": "llm_openai",
  "config": {
    "profile": "openai-4o",
    "openai-4o": { "apikey": "${ROCKETRIDE_OPENAI_KEY}" }
  }
}
```

Nodes use `${ENV_VAR}` substitution so the key itself never has to appear in the
`.pipe` file. Only `ROCKETRIDE_`-prefixed variables are substituted — a
reference to any other variable is replaced with `<REDACTED>`. See [Best Practices: Credential management](/guides/best-practices#credential-management)
for how to keep keys out of version control.

## Pipeline process isolation

Each running pipeline is a separate engine process (a task). A task does not
inherit the engine's full environment, only an allowlist:

- process basics: `PATH`, `HOME`, locale, TLS and proxy settings
- interpreter and ML runtime settings (`PYTHON*`, `HF_*`, `CUDA_*`, and similar)
- every `ROCKETRIDE_` variable except `ROCKETRIDE_DB_DSNS`, `ROCKETRIDE_DB_DSN`
  and `ROCKETRIDE_DB_RESOLVE_ERROR` (and the former broker names below), which
  the engine removes in any spelling. A task that uses a RocketRide database
  node then gets `ROCKETRIDE_DB_DSNS`, holding the DSN of each database the run
  was approved for, however the pipeline spells the node's provider (any case,
  or a `${ROCKETRIDE_*}` placeholder). Any other `ROCKETRIDE_DB_*` name passes
  through like the rest.
- what nodes and the task itself use directly: `RR_STORE_URL`,
  `RR_STORE_SECRET_KEY`, `RR_SIGNING_KEY`, `RR_BASE_URL`, `RR_CORS_ORIGINS`,
  `RR_OAUTH_BROKER_URL`, `RR_PROC_PRIVATE`, `MEDIA_TOOLKIT_FFMPEG`, `AWS_*`, and
  the API-key fallbacks individual node pages document (such as
  `OPENAI_API_KEY`)

Pipeline code can read everything on that list. Any other engine setting stays
in the engine.

The RocketRide cloud database broker is configured with the operator-only
settings `RR_DB_BROKER_URL` and `RR_DB_BROKER_TOKEN`. They are never
substituted into a pipeline, never returned or changed by the account
`get_env` and `set_env` commands, and never passed to a task, whatever
`RR_SUBPROCESS_ENV` allows. The engine refuses to start while the former names
`ROCKETRIDE_DB_BROKER_URL` or `ROCKETRIDE_DB_BROKER_TOKEN` are set, in its
environment or in its `.env` file, even next to the new names, and the
open-source `set_env` command refuses them: rename them in the deployment
configuration and secret mapping in the same change. A hosted engine without
the broker settings logs a warning at startup, and its RocketRide database
nodes report the missing broker configuration when a task starts.

The open-source `set_env` command replaces the engine's whole set of
`ROCKETRIDE_` settings, in its environment and in its `.env` file, with the
names it is given that start with `ROCKETRIDE_` (in capitals), one exact
assignment per line, and ignores the other names it is given. Every
`ROCKETRIDE_` name it is not given is removed from the environment, and its
`NAME=value` lines are removed from the `.env` file (a line written as
`export NAME=value` stays). The one exception is the engine's API key,
`ROCKETRIDE_APIKEY`: a request that does not name it keeps it, in the
environment and in the `.env` file, wherever it was set, so no request can
switch off the key check by leaving the key out. A request without `env` is
handled as an empty object, not refused, so it removes every other
`ROCKETRIDE_` setting. The key is compared in constant time. It refuses the
whole request, changing nothing, when:

- `env` is not an object of names to values (`null`, for example);
- it would set `ROCKETRIDE_APIKEY` to an empty or blank value (a new non-empty
  key is accepted, which rotates it);
- a name is one of the broker settings or their former names, in any case or
  with surrounding whitespace (refused, not ignored);
- a `ROCKETRIDE_` name has nothing after the prefix, or anything other than
  ASCII letters, digits and underscores;
- a value given for a `ROCKETRIDE_` name is not a string, has a control
  character (U+0000 to U+001F or U+007F to U+009F), a Unicode line or
  paragraph separator (U+2028, U+2029) or a surrogate code point (U+D800 to
  U+DFFF, which UTF-8 cannot encode), or contains `${`, which the `.env`
  loader would expand when the engine starts;
- such a value would need quotes in the file (it starts or ends with
  whitespace, starts with a quote, or has whitespace before a `#`) and ends
  with a backslash.

The command writes the new `.env` file in full next to the one it replaces
(for a symlinked `.env`, next to the file the link points to), with that
file's permission bits, and then renames it into place. It therefore needs
write access to that directory, and it refuses an existing `.env` file it may
not write. On Linux and macOS, a new `.env` file is readable and writable only
by the engine's user. If the `.env` file cannot be read as UTF-8 or the new
one cannot be written in full, the command fails and leaves the engine's
environment and the `.env` file as they were.

Each RocketRide database node connects to the database its Database setting
chooses: the organization's (the default), the run's team's or the run's
user's. When a task starts, the engine authorizes every database the
pipeline's nodes choose against the task's own identity, resolves their
connections and hands them to the task in `ROCKETRIDE_DB_DSNS`; nothing else in
the pipeline, a node's configuration or the task's environment selects a
tenant. A task takes its connections from the engine alone: a database the
engine did not resolve for it is refused, and its database nodes never resolve
one themselves. The connection check that runs when a node's configuration is
saved resolves no database at all, so the engine's own environment cannot
select one either. The connection string the broker returns must require TLS:
an explicit `sslmode`
of `require`, `verify-ca` or `verify-full` is used as issued, a missing one
becomes `require`, and one that does not require TLS is refused unless every
host it names (including libpq's `host` and `hostaddr` parameters) is on the
loopback interface.

| Variable            | Effect                                                                                                                                                                                                        |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `RR_SUBPROCESS_ENV` | Extra variables to pass to tasks: names separated by commas or spaces, a trailing `*` for a prefix (`SLACK_BOT_TOKEN,GH_*`). A bare `*` passes the whole environment; use that only on a single-user install. |
| `RR_PROC_PRIVATE`   | `1` makes the engine and each task restrict their sensitive `/proc/<pid>` entries (environment, memory, open files) to root. Linux only. Hosted engines turn this on automatically.                           |

Set both in the engine's own environment or its `.env` file. Pipelines cannot
change `RR_` variables.

Limits of `RR_PROC_PRIVATE`:

- Entries such as `cmdline` and `status` stay readable to everyone.
- A process is covered only after its startup code has run, and only that
  process: other programs the engine or a task starts are not covered.
- While a crash dump is being written, the crashing process is readable again.
- Same-user debuggers (`gdb`, `py-spy`) can no longer attach, and the kernel
  writes no core dumps for these processes.
- A task that cannot make itself private exits without running pipeline code.
  If the engine itself cannot, it logs a warning and keeps serving.

For strict separation between pipelines, run them under different OS users or
in separate containers.

## Network exposure

The engine binds to `localhost` by default:

- **Port 5565** — WebSocket API (SDK / CLI connections).
- **Source-node HTTP endpoints** (Webhook, Chat, Dropper) — the port is set
  per node in the pipeline config; 5567 is the conventional choice used in
  examples and integrations, not a fixed engine bind.

Only the source-node HTTP port needs to be accessible to external callers when
you're using a webhook-based source. Port 5565 is a management interface;
expose it only to trusted clients on a private network or behind a VPN.

For production deployments, put the engine behind a reverse proxy (nginx,
Caddy, AWS ALB) that terminates TLS and enforces rate limiting before traffic
reaches the engine.

## Endpoint authentication

When a Webhook, Chat, or Dropper source node starts, the engine generates two
credentials and writes them to the Project Log:

- **Public authorization key** - presented by external callers in the
  `Authorization: Bearer <key>` header. Safe to share with trusted API clients.
- **Private token** - the internal credential for the endpoint. Used by the SDK
  to connect to a running task via `--token`. Do not share this publicly.

The Project Log is local to the operator who started the pipeline (it is not a
shared or exportable log), so the private token is only visible to that
operator. Retrieve it from your own Project Log when you need to connect a client
with `--token`.

Both are generated fresh each time the pipeline starts. There is no persistent
credential to rotate — stopping and restarting the pipeline issues new
credentials automatically.

## MCP authentication

The [MCP server](/connect/mcp/stdio) authenticates callers in two ways:

- **`ROCKETRIDE_AUTH` / `ROCKETRIDE_APIKEY`** — the API key used to connect the
  MCP server to the RocketRide engine. Required; set in the environment.
- **`MCP_API_KEY`** — a Bearer token that clients must present to the MCP
  server when it is running in SSE (HTTP) mode. Optional for stdio mode,
  required for any network-exposed SSE deployment.

## Pipeline file security

A `.pipe` file is plain JSON. When you use `${ENV_VAR}` substitution, the key
stays in the environment and never touches disk in the pipeline file. When you
embed a key directly (for quick local testing), it is stored in plain text —
treat the file as a secret.

Do not commit `.pipe` files containing embedded credentials to version control.
Add them to `.gitignore`:

```gitignore
*.pipe
```

In CI/CD, pass the pipeline file through a secrets-expansion step before
passing it to `rocketride start`, or inject keys via environment variables and
use `${...}` references.

## Dependency scanning

The RocketRide codebase runs automated dependency scanning: CodeQL via
GitHub's default setup, plus Trivy and OpenSSF Scorecard on pushes to
`develop`/`main` and on scheduled runs. See [Security](/support/security-policy) for the
vulnerability reporting process and SLA.

## Related

- [Best Practices](/guides/best-practices): credential management patterns.
- [Self-hosting](/operate/self-hosting): network configuration.
- [MCP Server](/connect/mcp/stdio): MCP-specific authentication.
- [Security policy](/support/security-policy): vulnerability reporting.
