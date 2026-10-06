# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# =============================================================================

"""
Shared connection resolution for the RocketRide cloud database nodes.

``rocketride_sql``, ``rocketride_vector`` and ``rocketride_graph`` all connect
to the same per-tenant cloud database and take **no** connection config.  The
tenant is the organization that runs the task (its user only where there is no
organization).  Rather than reading host/user/password, the nodes take a ready
DSN for that tenant from the account layer.  Centralising that resolution here
gives the three nodes one identical seam — and one place for tests to inject a
fake resolver — so node code is byte-for-byte independent of which
``Account.resolve_db_dsn`` implementation (OSS stub, real SaaS, or fake) is live.

In the hosted path the task engine resolves the DSN server-side when a task
starts, from the task's own identity, and injects it as
``ROCKETRIDE_DB_DSN``; nodes never resolve identity themselves (identity rides
the task file since #1686 — the task engine does NOT set
``ROCKETRIDE_CLIENT_ID``).  A hosted engine's server process, where a node's
save-time ``validateConfig`` probe runs, resolves no tenant at all: it serves
every tenant and the probe carries none, so it reports the broker state
instead.  The env-based ``current_client_id`` accessor remains for the account
fallback used by the open-source server process and tests.
The account call is async while node lifecycle code (``beginGlobal`` /
``Store.__init__``) is synchronous, so it is bridged with ``asyncio.run`` —
safe only from a thread with no running loop, which is exactly how nodes are
constructed.
"""

import asyncio
import os
import sys
import urllib.parse

# Identity override consumed only by the account fallback (the open-source
# server process and tests; a hosted engine's server process never reads it).
# The task engine does NOT set this in node subprocesses:
# identity rides the task file (#1686) and the ROCKETRIDE_* env namespace is
# caller-influenced by design.
CLIENT_ID_ENV = 'ROCKETRIDE_CLIENT_ID'

# The task engine resolves the per-tenant DSN server-side at task start (only
# the server process has SaaS account context) and injects it here for
# pipelines that contain RocketRide cloud DB nodes.
DB_DSN_ENV = 'ROCKETRIDE_DB_DSN'

# When server-side resolution fails (e.g. a broker outage), the task engine
# passes the reason down here instead of a DSN, so the node can report the
# real cause rather than the misleading "sign into RocketRide cloud" error.
DB_RESOLVE_ERROR_ENV = 'ROCKETRIDE_DB_RESOLVE_ERROR'

# A hosted engine starts each task process with this flag
# (task_engine.CONST_HOSTED_CHILD_FLAG); its own server process never has it.
HOSTED_CHILD_FLAG = '--hosted'

# What a hosted engine without broker settings passes in
# ROCKETRIDE_DB_RESOLVE_ERROR at task start
# (task_engine.CONST_DB_BROKER_UNCONFIGURED). The server-process check reports
# the same words.
BROKER_UNCONFIGURED = 'the RocketRide cloud database broker is not configured on this server'


class ResolvedAtTaskStart(ValueError):
    """Nothing to check yet: a hosted engine resolves the database when a task starts.

    Raised by :func:`resolve_rocketride_dsn` in a hosted engine's server
    process (a DB node's save-time ``validateConfig`` probe) when DSNs can be
    resolved there at task start (the broker is configured, or the account
    resolves DSNs itself). A subclass of ValueError, so the nodes' probes show
    it as their usual warning.
    """


def _run_async(async_fn, *args):
    """Run an async callable from synchronous node lifecycle code.

    Only safe to call from a thread with no running event loop — node
    ``beginGlobal`` / ``Store.__init__`` are invoked synchronously by the
    engine, which is the supported caller. Pre-check before creating the
    coroutine so a misuse surfaces with a clear message and cannot leak an
    unawaited coroutine.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            'resolve_rocketride_dsn must not be called from a thread with a running event loop; '
            'RocketRide DB node lifecycle methods are constructed synchronously by the engine.'
        )
    return asyncio.run(async_fn(*args))


def current_client_id() -> str:
    """Return the tenant id for the account fallback, from ``ROCKETRIDE_CLIENT_ID``.

    Only the open-source server process and tests reach it: a task process
    gets its DSN from the task engine, and a hosted engine's server process
    resolves no tenant (see :func:`resolve_rocketride_dsn`).

    Raises:
        ValueError: if the identity env var is missing — which normally means
            the node is running outside the task engine, or the connection is
            not signed into RocketRide cloud.
    """
    client_id = os.environ.get(CLIENT_ID_ENV, '').strip()
    if not client_id:
        raise ValueError(
            f'{CLIENT_ID_ENV} is not set; RocketRide cloud DB nodes require a signed-in RocketRide cloud identity'
        )
    return client_id


def to_sqlalchemy_url(dsn: str) -> str:
    """Normalise a libpq URL DSN to a SQLAlchemy psycopg2 URL.

    ``psycopg2.connect`` accepts a bare ``postgresql://`` / ``postgres://`` URL,
    but SQLAlchemy's ``create_engine`` needs an explicit driver in the scheme.
    A DSN that already names a driver (``postgresql+psycopg2://``) or is a
    key/value libpq string (``host=... dbname=...``) is passed through
    unchanged.
    """
    if '+' in dsn.split(':', 1)[0]:
        # Scheme already carries a driver (e.g. postgresql+psycopg2://).
        return dsn
    for prefix in ('postgresql://', 'postgres://'):
        if dsn.startswith(prefix):
            return 'postgresql+psycopg2://' + dsn[len(prefix) :]
    return dsn


def _is_hosted_server() -> bool:
    """True in the server process of a hosted (multi-tenant) engine.

    Hosted means what it means to the task engine and to the startup broker
    warning: the engine's own ``--saas`` launch flag, or an account with the
    ``saas`` capability. A task process is never the server: a hosted engine
    starts each one with ``--hosted`` (pipeline arguments can add flags, not
    remove that one), and the task engine built its environment. The account
    layer is consulted only when already loaded, as it always is in the server
    process before any node runs, so this never imports it.
    """
    if HOSTED_CHILD_FLAG in sys.argv:
        return False
    if '--saas' in sys.argv:
        return True
    account = getattr(sys.modules.get('ai.account'), 'account', None)
    return 'saas' in (getattr(account, 'capabilities', None) or ())


def _hosted_server_error() -> ValueError:
    """The broker state, as a hosted engine's server-process check reports it."""
    from ai.account import account
    from ai.account.base import hosted_db_broker_warning

    # The broker settings exactly as task start reads them (the web server has
    # loaded the engine's .env by the time a node runs); nothing else in the
    # server's environment is read.
    if hosted_db_broker_warning(account, sys.argv, os.environ) is not None:
        return ValueError(f'The database connection cannot be checked: {BROKER_UNCONFIGURED}')
    return ResolvedAtTaskStart(
        'The database connection is checked when a task starts, against the database of the '
        'organization that runs the pipeline'
    )


def resolve_rocketride_dsn() -> str:
    """Resolve the libpq DSN of the current tenant's RocketRide cloud database.

    The tenant is the organization that runs the task (its user only where
    there is no organization). Delivery order:

    0. A hosted engine's server process (a node's save-time ``validateConfig``
       probe) resolves nothing: it serves every tenant and the probe carries
       none, so it never takes a DSN or an identity from its own environment.
       It raises with the broker state instead: ``ValueError`` naming
       :data:`BROKER_UNCONFIGURED` (the words a node reports at task start),
       or :class:`ResolvedAtTaskStart` when DSNs can be resolved at task start.
    1. ``ROCKETRIDE_DB_DSN`` env — the production path. The task engine
       resolves the DSN server-side at task start (the SaaS account context
       exists only in the server process; node subprocesses always see the
       OSS account) and injects it here at task start. In the open-source
       server process it is the single tenant's DSN for local development.
    2. ``ROCKETRIDE_DB_RESOLVE_ERROR`` env — why the task engine could not
       resolve one at task start.
    3. ``Account.resolve_db_dsn(client_id)`` — fallback for the open-source
       server process (or tests injecting a fake account). On an unconfigured
       open-source build this raises the cloud-sign-in error.

    Returns the raw DSN (URL form, directly usable by ``psycopg2.connect``).
    Callers that need a SQLAlchemy engine URL should wrap the result in
    :func:`to_sqlalchemy_url`.
    """
    if _is_hosted_server():
        raise _hosted_server_error()

    injected = os.environ.get(DB_DSN_ENV, '').strip()
    if injected:
        return injected

    # Server-side resolution was attempted and failed: report that failure,
    # not the sign-in error the account fallback below would produce (the
    # task engine scrubs the broker env from node subprocesses, so the
    # fallback cannot succeed here anyway).
    resolve_error = os.environ.get(DB_RESOLVE_ERROR_ENV, '').strip()
    if resolve_error:
        raise ValueError(f'RocketRide cloud database resolution failed at task start: {resolve_error}')

    # Lazy import: ai.common is imported very early, and ai.account pulls in the
    # OSS/SaaS overlay — importing at module load risks a cycle.
    from ai.account import account

    dsn = _run_async(account.resolve_db_dsn, current_client_id())
    if not dsn or not isinstance(dsn, str):
        raise ValueError('Account.resolve_db_dsn returned an empty DSN')
    return dsn


def parse_dsn_fields(dsn: str) -> dict:
    """Best-effort parse of a URL-form DSN into host/user/password/database.

    Used only to populate cosmetic / bookkeeping fields (e.g. the base class's
    ``database`` used in log messages and the vector node's connection subKey).
    The DSN itself remains the source of truth for the actual connection.
    Non-URL DSNs yield empty fields.
    """
    empty = {'host': '', 'port': None, 'user': '', 'password': '', 'database': ''}
    try:
        parsed = urllib.parse.urlparse(dsn)
    except ValueError:
        # e.g. mismatched IPv6 brackets — urlparse itself rejects the URL.
        return empty
    if not parsed.scheme:
        return empty
    # hostname/port validate lazily and raise ValueError on malformed
    # authorities (bad bracket host, non-numeric or out-of-range port); these
    # fields are cosmetic, so degrade per-field rather than fail node
    # construction.
    try:
        host = parsed.hostname or ''
    except ValueError:
        host = ''
    try:
        port = parsed.port
    except ValueError:
        port = None
    return {
        'host': host,
        'port': port,
        'user': urllib.parse.unquote(parsed.username) if parsed.username else '',
        'password': urllib.parse.unquote(parsed.password) if parsed.password else '',
        'database': (parsed.path or '').lstrip('/'),
    }
