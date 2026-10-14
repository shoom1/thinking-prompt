"""Tests for the repaint after the terminal gets smaller (thinking_prompt.resize)."""
from __future__ import annotations

import asyncio

from prompt_toolkit.data_structures import Size

from thinking_prompt.resize import ShrinkRepaint

WIDE = Size(rows=24, columns=80)


def _watch() -> tuple[ShrinkRepaint, list[bool]]:
    repaints: list[bool] = []
    return ShrinkRepaint(lambda: repaints.append(True), 0.01), repaints


async def _fired(watch: ShrinkRepaint) -> None:
    """Wait for the repaint ``watch`` has waiting to happen."""
    deadline = asyncio.get_running_loop().time() + 2
    while watch._handle is not None:
        assert asyncio.get_running_loop().time() < deadline, "the repaint never came"
        await asyncio.sleep(0.005)


class TestShrinkRepaint:
    async def test_a_narrower_terminal_repaints_once_it_settles(self):
        watch, repaints = _watch()
        watch.seen(WIDE)
        watch.seen(Size(rows=24, columns=60))
        assert repaints == []  # not until the size holds
        await _fired(watch)
        assert repaints == [True]

    async def test_a_shorter_terminal_repaints(self):
        watch, repaints = _watch()
        watch.seen(WIDE)
        watch.seen(Size(rows=10, columns=80))
        await _fired(watch)
        assert repaints == [True]

    async def test_a_growing_terminal_does_not_repaint(self):
        watch, repaints = _watch()
        watch.seen(WIDE)
        watch.seen(Size(rows=30, columns=100))
        watch.seen(Size(rows=30, columns=100))
        assert watch._handle is None and repaints == []

    async def test_a_resize_burst_repaints_once_after_the_last_change(self):
        watch, repaints = _watch()
        watch.seen(WIDE)
        watch.seen(Size(rows=24, columns=60))
        first = watch._handle
        # Growing back within the burst still repaints (the shrink left rows
        # behind), but only after the wait starts over.
        watch.seen(Size(rows=24, columns=90))
        assert first is not None and first.cancelled()
        assert watch._handle is not None and watch._handle is not first
        await _fired(watch)
        assert repaints == [True]

    async def test_each_settled_shrink_repaints(self):
        watch, repaints = _watch()
        watch.seen(WIDE)
        watch.seen(Size(rows=24, columns=60))
        await _fired(watch)
        watch.seen(Size(rows=24, columns=70))
        assert watch._handle is None  # growing alone doesn't
        watch.seen(Size(rows=20, columns=70))
        await _fired(watch)
        assert repaints == [True, True]

    async def test_cancel_drops_a_pending_repaint(self):
        watch, repaints = _watch()
        watch.seen(WIDE)
        watch.seen(Size(rows=24, columns=60))
        watch.cancel()
        assert watch._handle is None
        await asyncio.sleep(0.05)
        assert repaints == []

    async def test_after_cancel_the_next_size_is_a_first_sighting(self):
        """A new run of the app draws a fresh frame: a shrink between runs
        leaves nothing behind to repaint."""
        watch, repaints = _watch()
        watch.seen(WIDE)
        watch.cancel()
        watch.seen(Size(rows=24, columns=60))
        assert watch._handle is None and repaints == []
