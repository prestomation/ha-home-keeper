"""The ``blockbuster`` fixture in conftest.py must be on, or it proves nothing."""

from __future__ import annotations

import asyncio
import time

import pytest

# The fixture is a no-op without blockbuster (a bare install). Every lane that installs
# requirements-test.txt has it, so these guard tests run there.
BlockingError = pytest.importorskip("blockbuster").BlockingError


def test_blockbuster_finds_a_blocking_call_on_the_loop():
    async def blocking() -> None:
        time.sleep(0.01)  # noqa: ASYNC251 - the blocking call is the point

    with pytest.raises(BlockingError):
        asyncio.run(blocking())


def test_blockbuster_allows_the_same_call_in_a_worker_thread():
    async def offloaded() -> str:
        await asyncio.to_thread(time.sleep, 0.01)
        return "done"

    assert asyncio.run(offloaded()) == "done"


def test_blockbuster_ignores_a_call_with_no_loop():
    time.sleep(0.001)
