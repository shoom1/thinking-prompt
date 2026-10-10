"""On-demand redraws: writes ask for a redraw, animations ask for their next
frame while they're drawn, and nothing redraws on a fixed timer."""
from __future__ import annotations

import asyncio

import pytest

from thinking_prompt import layout
from thinking_prompt.frames import POLL_INTERVAL, FrameScheduler
from thinking_prompt.layout import ThinkingHeader
from thinking_prompt.manager import ThinkingBoxManager


class _Counter:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


class _Clock:
    """Stands in for time.monotonic() in the layout module."""

    def __init__(self, now: float) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    fake = _Clock(10.0)
    monkeypatch.setattr(layout, "time", fake)
    return fake


class TestFrameScheduler:
    async def test_requests_merge_into_one_redraw_at_the_earliest(self):
        redraws = _Counter()
        frames = FrameScheduler(redraws)

        frames.redraw_in(0.05)
        frames.redraw_in(0.2)  # later than the pending one: covered by it
        frames.redraw_in(0.02)  # sooner: moves it
        await asyncio.sleep(0.04)
        assert redraws.calls == 1

        await asyncio.sleep(0.25)
        assert redraws.calls == 1  # nothing asked again: nothing ticks

    async def test_cancel_drops_the_pending_redraw(self):
        redraws = _Counter()
        frames = FrameScheduler(redraws)
        frames.redraw_in(0.02)
        frames.cancel()
        await asyncio.sleep(0.05)
        assert redraws.calls == 0

    def test_a_request_outside_an_event_loop_is_ignored(self):
        FrameScheduler(_Counter()).redraw_in(0.1)

    def test_redraw_asks_now(self):
        redraws = _Counter()
        FrameScheduler(redraws).redraw()
        assert redraws.calls == 1

    def test_a_request_left_on_a_finished_loop_does_not_block_new_ones(self):
        redraws = _Counter()
        frames = FrameScheduler(redraws)

        async def ask_and_leave() -> None:
            frames.redraw_in(0.2)  # never fires: this loop ends first

        async def ask_and_wait() -> None:
            frames.redraw_in(0.3)
            await asyncio.sleep(0.4)

        asyncio.run(ask_and_leave())
        asyncio.run(ask_and_wait())
        assert redraws.calls == 1


class TestSpinnerFrames:
    def test_frames_step_once_per_interval_from_the_first(self, clock: _Clock):
        header = ThinkingHeader(text="T", frames=("a", "b", "c"), animation_interval=0.5)
        shown = []
        for now in (10.0, 10.5, 11.25, 11.5):
            clock.now = now
            shown.append(header._get_current_frame())
        assert shown == ["a", "b", "c", "a"]

    def test_reset_starts_over_at_the_first_frame(self, clock: _Clock):
        header = ThinkingHeader(text="T", frames=("a", "b", "c"), animation_interval=0.5)
        header._get_current_frame()
        clock.now = 10.5
        assert header._get_current_frame() == "b"
        header.reset()
        clock.now = 11.0
        assert header._get_current_frame() == "a"

    def test_drawing_asks_for_the_next_frame(self, clock: _Clock):
        asked: list[float] = []
        header = ThinkingHeader(
            text="T", frames=("a", "b"), animation_interval=0.5, request_frame=asked.append
        )
        clock.now = 10.2
        header.get_formatted_text(40)
        (delay,) = asked
        assert 0.3 <= delay < 0.32  # the next frame is due at 10.5

    def test_spinners_started_apart_ask_for_the_same_redraw(self, clock: _Clock):
        """They step on one shared clock, so N spinners cost one redraw per frame."""
        asked: list[float] = []
        first = ThinkingHeader(text="A", animation_interval=0.5, request_frame=asked.append)
        clock.now = 10.0
        first.get_formatted_text(40)
        second = ThinkingHeader(text="B", animation_interval=0.5, request_frame=asked.append)
        clock.now = 10.3
        asked.clear()
        first.get_formatted_text(40)
        second.get_formatted_text(40)
        assert len(asked) == 2 and asked[0] == asked[1]

    def test_a_header_without_frames_asks_for_nothing(self):
        asked: list[float] = []
        header = ThinkingHeader(text="T", frames=(), request_frame=asked.append)
        header.get_formatted_text(40)
        assert asked == []


class TestBoxRedraws:
    def test_writes_ask_for_a_redraw(self):
        redraws = _Counter()
        manager = ThinkingBoxManager(frames=FrameScheduler(redraws))
        box = manager.create_box()
        assert box.streaming_content is not None

        box.streaming_content.append("a\n")
        box.streaming_content.set_line(0, "b")
        box.streaming_content.clear()

        assert redraws.calls == 3

    def test_a_box_fed_by_a_callback_asks_to_be_polled_when_drawn(self):
        asked: list[float] = []
        frames = FrameScheduler(_Counter())
        frames.redraw_in = asked.append  # type: ignore[method-assign]
        manager = ThinkingBoxManager(frames=frames)
        box = manager.create_box(lambda: "x\n")

        box.control.create_content(40, 5)

        assert asked == [POLL_INTERVAL]

    def test_a_box_written_through_its_handle_is_not_polled(self):
        asked: list[float] = []
        frames = FrameScheduler(_Counter())
        frames.redraw_in = asked.append  # type: ignore[method-assign]
        manager = ThinkingBoxManager(frames=frames)
        box = manager.create_box()
        assert box.streaming_content is not None
        box.streaming_content.append("x\n")

        box.control.create_content(40, 5)

        assert asked == []
