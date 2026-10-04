# =============================================================================
# RocketRide Engine
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

"""A small bounded pool of exclusively checked-out database connections.

Tool calls on one node run in parallel on worker threads. A DB-API connection
is thread-safe, but every cursor on it shares ONE transaction, so two calls on
one shared connection interleave inside the same transaction: one call's
rollback undoes the other's work, and per-transaction settings (``READ ONLY``,
``SET LOCAL statement_timeout``) apply to whichever call happens to open the
transaction. The fix is ownership: each call checks out a connection that no
other call can touch until it is returned, runs its own transaction, and gives
the connection back clean.

The pool is driver-agnostic. The caller supplies:

- ``connect()`` — open a new connection;
- ``reset(conn)`` — return a used connection to a clean idle state (e.g.
  rollback) or raise if it cannot; a connection whose reset raises is closed
  and dropped;
- ``is_usable(conn)`` — cheap local check before reuse (no round trip);
- ``close(conn)`` — close quietly.

Waiting is bounded: :meth:`ConnectionPool.connection` raises
:class:`PoolTimeout` when no connection frees up within ``acquire_timeout_s``.
After :meth:`ConnectionPool.close`, idle connections are closed at once and
in-use ones as they are returned.
"""

from __future__ import annotations

import threading
import time

from contextlib import contextmanager
from typing import Any, Callable, Iterator, List


class PoolTimeout(TimeoutError):
    """No connection became available within the acquire timeout."""


class PoolClosed(RuntimeError):
    """The pool was closed (node shutdown); no new connections are handed out."""


class ConnectionPool:
    """Bounded pool; each checkout is exclusive until returned."""

    def __init__(
        self,
        connect: Callable[[], Any],
        *,
        max_size: int,
        acquire_timeout_s: float,
        reset: Callable[[Any], None],
        is_usable: Callable[[Any], bool],
        close: Callable[[Any], None],
    ) -> None:
        if max_size < 1:
            raise ValueError('max_size must be >= 1')
        self._connect = connect
        self._reset = reset
        self._is_usable = is_usable
        self._close_conn = close
        self.max_size = max_size
        self.acquire_timeout_s = acquire_timeout_s
        self._idle: List[Any] = []
        # Connections handed out or being opened right now; bounded by max_size
        # together with the idle list.
        self._checked_out = 0
        self._closed = False
        # id() of checked-out connections marked broken by discard().
        self._broken: set = set()
        self._cond = threading.Condition()

    # ------------------------------------------------------------------
    # Introspection (tests, diagnostics)
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        """Connections that currently exist (idle + checked out)."""
        with self._cond:
            return len(self._idle) + self._checked_out

    @property
    def idle(self) -> int:
        with self._cond:
            return len(self._idle)

    @property
    def closed(self) -> bool:
        return self._closed

    # ------------------------------------------------------------------
    # Checkout
    # ------------------------------------------------------------------

    @contextmanager
    def connection(self) -> Iterator[Any]:
        """Check out a connection exclusively for the duration of the block.

        The block owns the connection's transaction. On exit — normal or by
        exception — the connection is reset (rolled back) and reused; if it was
        :meth:`discard`-ed, the reset fails, or it is no longer usable, it is
        closed and dropped instead.
        """
        conn = self._acquire()
        try:
            yield conn
        finally:
            self._release(conn)

    def discard(self, conn: Any) -> None:
        """Mark a checked-out connection as broken; it is closed on release.

        Call this for connection-level failures (dropped socket, server
        restart, an interrupted protocol state), where a rollback cannot be
        trusted to leave a clean session.
        """
        with self._cond:
            self._broken.add(id(conn))

    def _acquire(self) -> Any:
        deadline = time.monotonic() + self.acquire_timeout_s
        with self._cond:
            while True:
                if self._closed:
                    raise PoolClosed('the database connection pool is closed (the node is shutting down)')
                while self._idle:
                    candidate = self._idle.pop()
                    if self._is_usable(candidate):
                        self._checked_out += 1
                        return candidate
                    # Died while idle (server restart, idle timeout): drop it
                    # and keep looking; a fresh one is opened below if needed.
                    self._close_quietly(candidate)
                if self._checked_out < self.max_size:
                    # Reserve the slot before the (slow) connect, outside the lock.
                    self._checked_out += 1
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PoolTimeout(
                        f'Timed out after {self.acquire_timeout_s:g} s waiting for a database connection '
                        f'({self.max_size} in use)'
                    )
                self._cond.wait(remaining)
        try:
            return self._connect()
        except BaseException:
            with self._cond:
                self._checked_out -= 1
                self._cond.notify()
            raise

    def _release(self, conn: Any) -> None:
        with self._cond:
            keep = id(conn) not in self._broken
            self._broken.discard(id(conn))
        if keep:
            try:
                self._reset(conn)
            except Exception:
                keep = False
        if keep and not self._is_usable(conn):
            keep = False
        if not keep:
            self._close_quietly(conn)
        with self._cond:
            self._checked_out -= 1
            if keep and not self._closed:
                self._idle.append(conn)
            elif keep:
                self._close_quietly(conn)
            self._cond.notify()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close idle connections now; checked-out ones close when returned."""
        with self._cond:
            self._closed = True
            idle, self._idle = self._idle, []
            self._cond.notify_all()
        for conn in idle:
            self._close_quietly(conn)

    def _close_quietly(self, conn: Any) -> None:
        try:
            self._close_conn(conn)
        except Exception:
            pass
