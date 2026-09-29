"""The single caching primitive behind every endpoint."""
from __future__ import annotations

import asyncio

import pytest

from app import cache


def run(coro):
    return asyncio.run(coro)


def counter():
    calls = []

    async def compute(value="v", delay=0.0):
        calls.append(value)
        if delay:
            await asyncio.sleep(delay)
        return value

    return calls, compute


def test_same_key_computes_once():
    memo = cache.Memo()
    calls, compute = counter()

    async def go():
        a = await memo.get("k", compute)
        b = await memo.get("k", compute)
        return a, b

    assert run(go()) == ("v", "v") and calls == ["v"]


def test_new_key_recomputes_and_old_keys_age_out():
    memo = cache.Memo(max_keys=2)
    calls, compute = counter()

    async def go():
        for key in ("a", "b", "c", "a"):
            await memo.get(key, lambda k=key: compute(k))

    run(go())
    assert calls == ["a", "b", "c", "a"]  # "a" was evicted by "c", so recomputed


def test_concurrent_callers_share_one_computation():
    memo = cache.Memo()
    calls, compute = counter()

    async def go():
        return await asyncio.gather(*(memo.get("k", lambda: compute("v", 0.01)) for _ in range(5)))

    assert run(go()) == ["v"] * 5 and calls == ["v"]


def test_different_keys_do_not_block_each_other():
    memo = cache.Memo()
    order = []

    async def slow():
        await asyncio.sleep(0.05)
        order.append("slow")
        return 1

    async def fast():
        order.append("fast")
        return 2

    async def go():
        await asyncio.gather(memo.get("team-147", slow), memo.get("team-139", fast))

    run(go())
    assert order == ["fast", "slow"]


def test_ttl_expiry(monkeypatch):
    memo = cache.Memo(ttl=10)
    calls, compute = counter()
    now = [1000.0]
    monkeypatch.setattr(cache.time, "monotonic", lambda: now[0])

    async def go():
        await memo.get("k", compute)
        now[0] += 9
        await memo.get("k", compute)
        now[0] += 2
        await memo.get("k", compute)

    run(go())
    assert len(calls) == 2


def test_store_if_declines_partial_results():
    memo = cache.Memo()
    results = iter([{"complete": False}, {"complete": True}])

    async def compute():
        return next(results)

    async def go():
        first = await memo.get("k", compute, store_if=lambda r: r["complete"])
        second = await memo.get("k", compute, store_if=lambda r: r["complete"])
        third = await memo.get("k", compute, store_if=lambda r: r["complete"])
        return first, second, third

    first, second, third = run(go())
    assert first == {"complete": False} and second == third == {"complete": True}


def test_errors_are_not_cached():
    memo = cache.Memo()
    attempts = []

    async def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("upstream down")
        return "ok"

    async def go():
        with pytest.raises(RuntimeError):
            await memo.get("k", flaky)
        return await memo.get("k", flaky)

    assert run(go()) == "ok"
