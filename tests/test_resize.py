"""Tests for the repaint after the terminal gets smaller (thinking_prompt.resize)."""
from __future__ import annotations

import asyncio

from prompt_toolkit.data_structures import Size

from thinking_prompt.resize import ShrinkRepaint

DELAY = 0.02


def _watch() -> tuple[ShrinkRepaint, list[bool]]:
    repaints: list[bool] = []
    return ShrinkRepaint(lambda: repaints.append(True), DELAY), repaints


async def _settle() -> None:
    await asyncio.sleep(DELAY * 4)


class TestShrinkRepaint:
    async def test_a_narrower_terminal_repaints_once_it_settles(self):
        watch, repaints = _watch()
        watch.seen(Size(rows=24, columns=80))
        watch.seen(Size(rows=24, columns=60))
        assert repaints == []
        await _settle()
        assert repaints == [True]

    async def test_a_shorter_terminal_repaints(self):
        watch, repaints = _watch()
        watch.seen(Size(rows=24, columns=80))
        watch.seen(Size(rows=10, columns=80))
        await _settle()
        assert repaints == [True]

    async def test_a_growing_terminal_does_not_repaint(self):
        watch, repaints = _watch()
        watch.seen(Size(rows=24, columns=80))
        watch.seen(Size(rows=30, columns=100))
        watch.seen(Size(rows=30, columns=100))
        await _settle()
        assert repaints == []

    async def test_a_resize_burst_repaints_once_after_the_last_change(self):
        watch, repaints = _watch()
        watch.seen(Size(rows=24, columns=80))
        watch.seen(Size(rows=24, columns=60))
        await asyncio.sleep(DELAY / 2)
        # Growing back within the burst still repaints: the shrink left rows behind.
        watch.seen(Size(rows=24, columns=90))
        await asyncio.sleep(DELAY / 2)
        assert repaints == []
        await _settle()
        assert repaints == [True]

    async def test_each_settled_shrink_repaints(self):
        watch, repaints = _watch()
        watch.seen(Size(rows=24, columns=80))
        watch.seen(Size(rows=24, columns=60))
        await _settle()
        watch.seen(Size(rows=24, columns=70))
        await _settle()
        assert repaints == [True]
        watch.seen(Size(rows=20, columns=70))
        await _settle()
        assert repaints == [True, True]

    async def test_cancel_drops_a_pending_repaint(self):
        watch, repaints = _watch()
        watch.seen(Size(rows=24, columns=80))
        watch.seen(Size(rows=24, columns=60))
        watch.cancel()
        await _settle()
        assert repaints == []
