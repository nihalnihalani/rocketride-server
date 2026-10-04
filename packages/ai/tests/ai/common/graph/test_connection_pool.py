# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""Unit tests for the bounded, exclusive-checkout connection pool (no database)."""

from __future__ import annotations

import threading
import time

import pytest

from ai.common.graph import connection_pool as pool_mod


class FakeConn:
    _next = 0

    def __init__(self):
        FakeConn._next += 1
        self.serial = FakeConn._next
        self.closed = False
        self.resets = 0
        self.fail_reset = False

    def reset(self):
        if self.fail_reset:
            raise RuntimeError('reset failed')
        self.resets += 1


def make_pool(max_size=2, timeout=1.0, connect=None):
    opened = []

    def _connect():
        conn = (connect or FakeConn)()
        opened.append(conn)
        return conn

    pool = pool_mod.ConnectionPool(
        _connect,
        max_size=max_size,
        acquire_timeout_s=timeout,
        reset=lambda c: c.reset(),
        is_usable=lambda c: not c.closed,
        close=lambda c: setattr(c, 'closed', True),
    )
    return pool, opened


def test_checkout_is_exclusive_and_bounded():
    pool, opened = make_pool(max_size=2)
    barrier = threading.Barrier(4)
    held = []
    lock = threading.Lock()
    peak = [0]
    active = [0]

    def worker():
        barrier.wait()
        with pool.connection() as conn:
            with lock:
                assert conn not in held, 'a connection was handed to two callers at once'
                held.append(conn)
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            with lock:
                held.remove(conn)
                active[0] -= 1

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert peak[0] == 2
    assert len(opened) == 2
    assert pool.size == 2 and pool.idle == 2


def test_connections_are_reset_and_reused():
    pool, opened = make_pool(max_size=1)
    with pool.connection() as first:
        pass
    with pool.connection() as second:
        pass
    assert first is second
    assert first.resets == 2
    assert len(opened) == 1


def test_exception_in_block_still_resets_and_reuses():
    pool, opened = make_pool(max_size=1)
    with pytest.raises(ValueError):
        with pool.connection():
            raise ValueError('query failed')
    with pool.connection() as conn:
        assert conn is opened[0]
    assert opened[0].resets == 2


def test_discarded_connection_is_closed_not_reused():
    pool, opened = make_pool(max_size=1)
    with pool.connection() as conn:
        pool.discard(conn)
    assert conn.closed
    assert pool.size == 0
    with pool.connection() as fresh:
        assert fresh is not conn
    assert len(opened) == 2


def test_failed_reset_drops_connection():
    pool, opened = make_pool(max_size=1)
    with pool.connection() as conn:
        conn.fail_reset = True
    assert conn.closed and pool.size == 0


def test_dead_idle_connection_is_replaced_on_checkout():
    pool, opened = make_pool(max_size=1)
    with pool.connection() as conn:
        pass
    conn.closed = True  # server dropped it while idle
    with pool.connection() as fresh:
        assert fresh is not conn
    assert pool.size == 1


def test_acquire_times_out_when_exhausted():
    pool, _ = make_pool(max_size=1, timeout=0.1)
    with pool.connection():
        started = time.monotonic()
        with pytest.raises(pool_mod.PoolTimeout):
            with pool.connection():
                pass
        assert time.monotonic() - started >= 0.09


def test_waiter_gets_connection_when_one_is_returned():
    pool, opened = make_pool(max_size=1, timeout=2.0)
    got = []
    with pool.connection() as conn:
        t = threading.Thread(target=lambda: got.append(pool.connection().__enter__()))
        t.start()
        time.sleep(0.05)
        assert not got
    t.join(2)
    assert got == [conn]


def test_connect_failure_releases_the_slot():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise OSError('connection refused')
        return FakeConn()

    pool, _ = make_pool(max_size=1, connect=flaky)
    with pytest.raises(OSError):
        with pool.connection():
            pass
    with pool.connection() as conn:
        assert isinstance(conn, FakeConn)


def test_close_closes_idle_now_and_in_use_on_return():
    pool, opened = make_pool(max_size=2)
    with pool.connection():
        pass
    idle_conn = opened[0]
    with pool.connection() as busy:
        assert busy is idle_conn
        with pool.connection() as other:
            pass
        pool.close()
        assert other.closed  # was idle at close time
        assert not busy.closed
    assert busy.closed
    with pytest.raises(pool_mod.PoolClosed):
        with pool.connection():
            pass


def test_close_wakes_waiters():
    pool, _ = make_pool(max_size=1, timeout=5.0)
    errors = []

    def waiter():
        try:
            with pool.connection():
                pass
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    with pool.connection():
        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.05)
        pool.close()
        t.join(2)
    assert errors and isinstance(errors[0], pool_mod.PoolClosed)


def test_invalid_size_rejected():
    with pytest.raises(ValueError):
        make_pool(max_size=0)
