"""Thinking box lifecycle: the shared expand mode, which task owns a box,
finished handles, and what happens to a box's content when it's cancelled."""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock

import pytest
from prompt_toolkit.keys import Keys

from thinking_prompt import ThinkingPromptSession
from thinking_prompt.thinking_control import ThinkingBoxControl
from tests.helpers import make_manager

LONG = "\n".join(f"line {i}" for i in range(40))
CANCELLED = "Operation cancelled...\n"


def _transcript(session: ThinkingPromptSession) -> list[str]:
    return [entry.text for entry in session._display.transcript.iter_entries()]


def _ctrl_c(session: ThinkingPromptSession):
    for binding in session.app.key_bindings.bindings:
        if binding.keys == (Keys.ControlC,):
            return binding.handler
    raise AssertionError("Ctrl+C binding not registered")


class TestExpandMode:
    """One expand mode for all boxes, kept by the manager (#1, #5)."""

    def test_mode_resets_when_the_last_box_finishes(self):
        manager = make_manager()
        box = manager.create_box(lambda: LONG)
        manager.toggle_all()
        assert manager.is_expanded

        manager.finish(box)

        assert manager.is_expanded is False
        assert manager.can_toggle() is False
        assert manager.create_box(lambda: LONG)._control.is_expanded is False

    def test_mode_holds_while_other_boxes_remain(self):
        manager = make_manager()
        a = manager.create_box(lambda: LONG)
        manager.create_box(lambda: LONG)
        manager.toggle_all()

        manager.finish(a)

        assert manager.is_expanded
        (left,) = manager.get_sorted_boxes()
        assert left._control.is_expanded

    def test_nothing_to_toggle_without_boxes_even_when_expanded(self):
        manager = make_manager()
        manager.expand_all()
        assert manager.can_toggle() is False

    def test_boxes_follow_the_one_shared_mode(self):
        manager = make_manager()
        a = manager.create_box(lambda: LONG)
        b = manager.create_box(lambda: LONG)

        manager.toggle_all()
        assert a._control.is_expanded and b._control.is_expanded
        manager.toggle_all()
        assert not a._control.is_expanded and not b._control.is_expanded

    def test_a_standalone_box_reads_its_expand_predicate(self):
        expanded = [False]
        control = ThinkingBoxControl(lambda: LONG, max_collapsed_lines=5, expanded=lambda: expanded[0])
        assert control.is_expanded is False
        expanded[0] = True
        assert control.is_expanded is True


class TestOwnership:
    """A box belongs to the task that created it (#2)."""

    async def test_a_handler_ending_leaves_a_live_background_box(self):
        session = ThinkingPromptSession()
        opened, gate = asyncio.Event(), asyncio.Event()

        async def background() -> None:
            async with session.thinking(title="Indexing") as ctx:
                ctx.append("indexed 1\n")
                opened.set()
                await gate.wait()

        task = asyncio.create_task(background())
        await asyncio.wait_for(opened.wait(), 1)

        async def handler(text: str) -> None:
            session.start_thinking(lambda: "mine\n")

        await session._run_handler(handler, "go")

        assert session._manager.active_count == 1  # the background box
        gate.set()
        await asyncio.wait_for(task, 1)
        assert any("indexed 1" in text for text in _transcript(session))

    async def test_a_handler_ending_finishes_boxes_whose_task_ended(self):
        session = ThinkingPromptSession()

        async def sub() -> None:
            session.start_thinking(lambda: "left open\n")

        await asyncio.create_task(sub())  # its task ends with the box open
        await session._run_handler(lambda text: None, "go")

        assert not session.is_thinking

    async def test_ctrl_c_during_a_handler_leaves_a_live_background_box(self):
        session = ThinkingPromptSession()
        opened, gate, started = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def background() -> None:
            async with session.thinking(title="Indexing") as ctx:
                ctx.append("indexed 1\n")
                opened.set()
                await gate.wait()

        bg = asyncio.create_task(background())
        await asyncio.wait_for(opened.wait(), 1)

        async def handler(text: str) -> None:
            async with session.thinking() as ctx:
                ctx.append("working\n")
                started.set()
                await asyncio.sleep(3600)

        run = asyncio.create_task(session._run_handler(handler, "go"))
        await asyncio.wait_for(started.wait(), 1)
        event = MagicMock()
        event.app = session.app
        _ctrl_c(session)(event)
        await asyncio.wait_for(run, 1)

        assert session._manager.active_count == 1  # the background box
        gate.set()
        await asyncio.wait_for(bg, 1)

    async def test_idle_ctrl_c_leaves_a_live_background_box(self):
        session = ThinkingPromptSession()
        opened, gate = asyncio.Event(), asyncio.Event()

        async def background() -> None:
            async with session.thinking(title="Indexing") as ctx:
                ctx.append("indexed 1\n")
                opened.set()
                await gate.wait()

        task = asyncio.create_task(background())
        await asyncio.wait_for(opened.wait(), 1)
        event = MagicMock()

        _ctrl_c(session)(event)

        assert session._manager.active_count == 1  # the background box
        assert CANCELLED not in _transcript(session)
        event.app.exit.assert_not_called()
        gate.set()
        await asyncio.wait_for(task, 1)
        assert sum("indexed 1" in text for text in _transcript(session)) == 1

    async def test_idle_ctrl_c_ends_the_boxes_nobody_else_will(self):
        """A box whose task ended, one with no known owner and one the
        app's own task opened are ended; a live task's box stays."""
        session = ThinkingPromptSession()
        session._app_task = asyncio.current_task()  # this test plays the app's task
        session.start_thinking().append("app's own\n")

        async def open_and_return() -> None:
            session.start_thinking().append("task ended\n")

        await asyncio.create_task(open_and_return())
        await asyncio.to_thread(lambda: session.start_thinking().append("from a thread\n"))

        gate = asyncio.Event()

        async def live() -> None:
            async with session.thinking() as ctx:
                ctx.append("still going\n")
                await gate.wait()

        task = asyncio.create_task(live())
        await asyncio.sleep(0)
        event = MagicMock()

        _ctrl_c(session)(event)

        transcript = _transcript(session)
        for text in ("app's own", "task ended", "from a thread"):
            assert sum(text in entry for entry in transcript) == 1
        assert transcript[-1] == CANCELLED
        assert not any("still going" in entry for entry in transcript)
        assert session._manager.active_count == 1
        event.app.exit.assert_not_called()
        gate.set()
        await asyncio.wait_for(task, 1)

    async def test_without_run_async_idle_ctrl_c_leaves_the_loops_own_box(self):
        """A session driven by prompt_async() alone has no app task: the
        task driving it is a live owner like any other."""
        session = ThinkingPromptSession()
        session.start_thinking().append("mine\n")
        await asyncio.to_thread(lambda: session.start_thinking().append("thread\n"))
        event = MagicMock()

        _ctrl_c(session)(event)

        assert session._manager.active_count == 1  # this task's box
        assert sum("thread" in text for text in _transcript(session)) == 1
        event.app.exit.assert_not_called()

    async def test_without_a_status_bar_idle_ctrl_c_still_does_not_exit(self):
        """Guard: the exit decision doesn't depend on the status bar."""
        session = ThinkingPromptSession(enable_status_bar=False)
        opened, gate = asyncio.Event(), asyncio.Event()

        async def background() -> None:
            async with session.thinking():
                opened.set()
                await gate.wait()

        task = asyncio.create_task(background())
        await asyncio.wait_for(opened.wait(), 1)
        event = MagicMock()

        _ctrl_c(session)(event)

        event.app.exit.assert_not_called()
        assert session.is_thinking
        gate.set()
        await asyncio.wait_for(task, 1)


class TestFinishedHandle:
    """A finished box's handle says so, and finishing again is harmless (#3)."""

    def test_is_finished(self):
        session = ThinkingPromptSession()
        ctx = session.start_thinking()
        assert ctx.is_finished is False
        ctx.finish()
        assert ctx.is_finished is True

    def test_finish_after_the_session_finished_the_box_returns_its_content(self):
        session = ThinkingPromptSession()
        ctx = session.start_thinking()
        ctx.append("partial\n")

        _ctrl_c(session)(MagicMock())

        assert ctx.is_finished
        assert ctx.finish() == "partial\n"


class TestCancelledContent:
    """Cancelled thinking is echoed, then 'Operation cancelled...' (#6)."""

    def test_ctrl_c_echoes_content_then_says_so(self):
        session = ThinkingPromptSession()
        session.start_thinking().append("half done\n")

        _ctrl_c(session)(MagicMock())

        transcript = _transcript(session)
        assert any("half done" in text for text in transcript)
        assert transcript[-1] == CANCELLED
        assert not any(text.startswith("[WARN]") for text in transcript)

    def test_one_line_after_several_boxes(self):
        session = ThinkingPromptSession()
        session.start_thinking().append("a\n")
        session.start_thinking().append("b\n")

        _ctrl_c(session)(MagicMock())

        transcript = _transcript(session)
        assert transcript.count(CANCELLED) == 1
        assert transcript[-1] == CANCELLED
        assert any("a" in text for text in transcript[:-1])
        assert any("b" in text for text in transcript[:-1])

    def test_cancelling_an_empty_box_still_says_so(self):
        session = ThinkingPromptSession()
        session.start_thinking()

        _ctrl_c(session)(MagicMock())

        assert _transcript(session) == [CANCELLED]

    async def test_ctrl_c_during_a_handler_says_so_once(self):
        session = ThinkingPromptSession()
        started = asyncio.Event()

        async def handler(text: str) -> None:
            async with session.thinking() as ctx:
                ctx.append("working\n")
                started.set()
                await asyncio.sleep(3600)

        run = asyncio.create_task(session._run_handler(handler, "go"))
        await asyncio.wait_for(started.wait(), 1)
        event = MagicMock()
        event.app = session.app
        _ctrl_c(session)(event)
        await asyncio.wait_for(run, 1)

        transcript = _transcript(session)
        assert sum("working" in text for text in transcript) == 1
        assert transcript.count(CANCELLED) == 1
        assert transcript[-1] == CANCELLED

    async def test_ctrl_c_says_so_once_after_the_boxes_of_the_handlers_subtasks(self):
        session = ThinkingPromptSession()
        opened: list[str] = []
        both_open = asyncio.Event()

        async def step(name: str) -> None:
            async with session.thinking() as ctx:
                ctx.append(f"{name} working\n")
                opened.append(name)
                if len(opened) == 2:
                    both_open.set()
                await asyncio.sleep(3600)

        async def handler(text: str) -> None:
            await asyncio.gather(step("a"), step("b"))

        run = asyncio.create_task(session._run_handler(handler, "go"))
        await asyncio.wait_for(both_open.wait(), 1)
        event = MagicMock()
        event.app = session.app
        _ctrl_c(session)(event)
        await asyncio.wait_for(run, 1)

        transcript = _transcript(session)
        assert transcript.count(CANCELLED) == 1
        assert transcript[-1] == CANCELLED
        assert any("a working" in text for text in transcript)
        assert any("b working" in text for text in transcript)

    async def test_a_cancelled_thinking_block_echoes_then_says_so(self):
        session = ThinkingPromptSession()
        opened = asyncio.Event()

        async def work() -> None:
            async with session.thinking() as ctx:
                ctx.append("step 1\n")
                opened.set()
                await asyncio.sleep(3600)

        task = asyncio.create_task(work())
        await asyncio.wait_for(opened.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        transcript = _transcript(session)
        assert any("step 1" in text for text in transcript)
        assert transcript[-1] == CANCELLED

    async def test_a_failing_thinking_block_echoes_without_the_cancel_line(self):
        session = ThinkingPromptSession()
        with pytest.raises(RuntimeError):
            async with session.thinking() as ctx:
                ctx.append("step 1\n")
                raise RuntimeError("boom")

        transcript = _transcript(session)
        assert any("step 1" in text for text in transcript)
        assert CANCELLED not in transcript

    async def test_a_handler_error_echoes_content_then_the_error(self):
        session = ThinkingPromptSession()

        async def handler(text: str) -> None:
            session.start_thinking().append("step 1\n")
            raise KeyError("x")

        await session._run_handler(handler, "go")

        transcript = _transcript(session)
        index = next(i for i, text in enumerate(transcript) if "step 1" in text)
        assert transcript[index + 1].startswith("[ERROR] Handler error: KeyError")
        assert CANCELLED not in transcript

    async def test_a_box_left_open_by_a_handler_is_finished_normally(self):
        session = ThinkingPromptSession()

        async def handler(text: str) -> None:
            session.start_thinking().append("result\n")

        await session._run_handler(handler, "go")

        transcript = _transcript(session)
        assert any("result" in text for text in transcript)
        assert CANCELLED not in transcript


class TestCallbackErrors:
    """A content callback that raises is logged once, not on every redraw (#7a)."""

    def test_a_raising_callback_is_logged_once(self, caplog):
        def boom() -> str:
            raise ValueError("bad")

        control = ThinkingBoxControl(boom, max_collapsed_lines=5)
        with caplog.at_level(logging.ERROR, logger="thinking_prompt"):
            for _ in range(5):
                control.create_content(40, 5)
                control.get_line_count(40)

        logged = [r for r in caplog.records if "content callback" in r.getMessage()]
        assert len(logged) == 1
