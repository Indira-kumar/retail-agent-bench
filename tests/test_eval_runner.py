from __future__ import annotations

import asyncio

from retail_eval.runner import run_bounded


async def test_run_bounded_limits_parallel_rooms() -> None:
    active = 0
    maximum = 0
    lock = asyncio.Lock()

    async def execute(value: int) -> int:
        nonlocal active, maximum
        async with lock:
            active += 1
            maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        async with lock:
            active -= 1
        return value * 2

    results = await run_bounded(range(10), concurrency=3, execute=execute)

    assert results == [value * 2 for value in range(10)]
    assert maximum == 3
