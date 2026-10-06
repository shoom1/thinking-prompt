"""Thinking box lifecycle: the shared expand mode, which task owns a box,
finished handles, and what happens to a box's content when it's cancelled."""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock

import pytest
from prompt_toolkit.keys import Keys

from thinking_prompt import AppInfo, ThinkingPromptSession
from thinking_prompt.manager import ThinkingBoxManager
from thinking_prompt.thinking import ThinkingBoxControl

LONG = "\n".join(f"line {i}" for i in range(40))
CANCELLED = "Operation cancelled...\n"


def _history(session: ThinkingPromptSession) -> list[str]:
    return [entry.text for entry in session._display.history.iter_entries()]


def _ctrl_c(session: ThinkingPromptSession):
    for binding in session.app.key_bindings.bindings:
        if binding.keys == (Keys.ControlC,):
            return binding.handler
    raise AssertionError("Ctrl+C binding not registered")


class TestExpandMode:
    """One expand mode for all boxes, kept by the manager (#1, #5)."""

    def test_mode_resets_when_the_last_box_finishes(self):
        manager = ThinkingBoxManager()
        manager.create_box(lambda: LONG)
        manager.toggle_all()
        assert manager.is_expanded

        manager.finish_all()

        assert manager.is_expanded is False
        assert manager.can_toggle() is False
        assert manager.create_box(lambda: LONG).control.is_expanded is False

    def test_mode_holds_while_other_boxes_remain(self):
        manager = ThinkingBoxManager()
        manager.create_box(lambda: LONG, box_id="a")
        manager.create_box(lambda: LONG, box_id="b")
        manager.toggle_all()

        manager.remove_box("a")

        assert manager.is_expanded
        (left,) = manager.get_sorted_boxes()
        assert left.control.is_expanded

    def test_nothing_to_toggle_without_boxes_even_when_expanded(self):
        manager = ThinkingBoxManager()
        manager.expand_all()
        assert manager.can_toggle() is False

    def test_boxes_follow_the_one_shared_mode(self):
        manager = ThinkingBoxManager()
        a = manager.create_box(lambda: LONG)
        b = manager.create_box(lambda: LONG)

        manager.toggle_all()
        assert a.control.is_expanded and b.control.is_expanded
        manager.toggle_all()
        assert not a.control.is_expanded and not b.control.is_expanded
        # A box can't leave the shared mode on its own.
        assert not hasattr(a.control, "toggle_expanded")

    def test_a_standalone_box_reads_its_expand_predicate(self):
        expanded = [False]
        control = ThinkingBoxControl(max_collapsed_lines=5, expanded=lambda: expanded[0])
        control.start(lambda: LONG)
        assert control.is_expanded is False
        expanded[0] = True
        assert control.is_expanded is True


class TestFullScreen:
    """Full screen expands every box, including ones started there (#4)."""

    def test_forced_mode_expands_every_box_including_new_ones(self):
        manager = ThinkingBoxManager()
        a = manager.create_box(lambda: LONG)

        manager.force_expanded(True)
        b = manager.create_box(lambda: LONG)
        assert manager.is_expanded
        assert a.control.is_expanded and b.control.is_expanded

        manager.force_expanded(False)
        assert not a.control.is_expanded and not b.control.is_expanded

    def test_leaving_full_screen_restores_the_users_mode(self):
        manager = ThinkingBoxManager()
        a = manager.create_box(lambda: LONG)
        manager.toggle_all()

        manager.force_expanded(True)
        manager.force_expanded(False)

        assert a.control.is_expanded

    def test_session_boxes_started_in_full_screen_are_expanded(self):
        session = ThinkingPromptSession(app_info=AppInfo(name="t", fullscreen_enabled=True))
        session.switch_to_fullscreen()
        session.start_thinking(lambda: LONG)
        (box,) = session._manager.get_sorted_boxes()
        assert box.control.is_expanded

        session.switch_to_prompt()
        assert not box.control.is_expanded


class TestOwnership:
    """A box belongs to the task that created it (#2)."""

    async def test_box_remembers_the_task_that_created_it(self):
        manager = ThinkingBoxManager()
        assert manager.create_box(lambda: "x").owner is asyncio.current_task()

    def test_box_created_outside_asyncio_has_no_owner(self):
        assert ThinkingBoxManager().create_box(lambda: "x").owner is None

    def test_finish_all_can_pick_boxes(self):
        manager = ThinkingBoxManager()
        manager.create_box(lambda: "a", box_id="a")
        manager.create_box(lambda: "b", box_id="b")

        results = manager.finish_all(where=lambda box: box.box_id == "a")

        assert [r[0] for r in results] == ["a"]
        assert [box.box_id for box in manager.get_sorted_boxes()] == ["b"]

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
        assert any("indexed 1" in text for text in _history(session))

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


class TestFinishedHandle:
    """A finished box's handle says so, and finishing again is harmless (#3)."""

    def test_is_finished(self):
        session = ThinkingPromptSession()
        ctx = session.start_thinking()
        assert ctx.is_finished is False
        ctx.finish()
        assert ctx.is_finished is True

    def test_finish_is_idempotent_and_returns_the_content(self):
        session = ThinkingPromptSession()
        ctx = session.start_thinking()
        ctx.append("hello\n")

        assert ctx.finish() == "hello\n"
        entries = len(_history(session))
        assert ctx.finish() == "hello\n"
        assert len(_history(session)) == entries  # not echoed twice

    def test_finish_after_the_session_finished_the_box_returns_its_content(self):
        session = ThinkingPromptSession()
        ctx = session.start_thinking()
        ctx.append("partial\n")

        _ctrl_c(session)(MagicMock())

        assert ctx.is_finished
        assert ctx.finish() == "partial\n"

    def test_writes_after_finish_log_a_warning_once(self, caplog):
        session = ThinkingPromptSession()
        ctx = session.start_thinking()
        ctx.finish()

        with caplog.at_level(logging.WARNING, logger="thinking_prompt"):
            ctx.append("late\n")
            ctx.set_line(0, "late")
            ctx.set_title("late")

        warnings = [r for r in caplog.records if "already finished" in r.getMessage()]
        assert len(warnings) == 1


class TestCancelledContent:
    """Cancelled thinking is echoed, then 'Operation cancelled...' (#6)."""

    def test_ctrl_c_echoes_content_then_says_so(self):
        session = ThinkingPromptSession()
        session.start_thinking().append("half done\n")

        _ctrl_c(session)(MagicMock())

        history = _history(session)
        assert any("half done" in text for text in history)
        assert history[-1] == CANCELLED
        assert not any(text.startswith("[WARN]") for text in history)

    def test_one_line_after_several_boxes(self):
        session = ThinkingPromptSession()
        session.start_thinking().append("a\n")
        session.start_thinking().append("b\n")

        _ctrl_c(session)(MagicMock())

        history = _history(session)
        assert history.count(CANCELLED) == 1
        assert history[-1] == CANCELLED
        assert any("a" in text for text in history[:-1])
        assert any("b" in text for text in history[:-1])

    def test_cancelling_an_empty_box_still_says_so(self):
        session = ThinkingPromptSession()
        session.start_thinking()

        _ctrl_c(session)(MagicMock())

        assert _history(session) == [CANCELLED]

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

        history = _history(session)
        assert sum("working" in text for text in history) == 1
        assert history.count(CANCELLED) == 1
        assert history[-1] == CANCELLED

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

        history = _history(session)
        assert history.count(CANCELLED) == 1
        assert history[-1] == CANCELLED
        assert any("a working" in text for text in history)
        assert any("b working" in text for text in history)

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

        history = _history(session)
        assert any("step 1" in text for text in history)
        assert history[-1] == CANCELLED

    async def test_a_failing_thinking_block_echoes_without_the_cancel_line(self):
        session = ThinkingPromptSession()
        with pytest.raises(RuntimeError):
            async with session.thinking() as ctx:
                ctx.append("step 1\n")
                raise RuntimeError("boom")

        history = _history(session)
        assert any("step 1" in text for text in history)
        assert CANCELLED not in history

    async def test_a_handler_error_echoes_content_then_the_error(self):
        session = ThinkingPromptSession()

        async def handler(text: str) -> None:
            session.start_thinking().append("step 1\n")
            raise KeyError("x")

        await session._run_handler(handler, "go")

        history = _history(session)
        index = next(i for i, text in enumerate(history) if "step 1" in text)
        assert history[index + 1].startswith("[ERROR] Handler error: KeyError")
        assert CANCELLED not in history

    async def test_a_box_left_open_by_a_handler_is_finished_normally(self):
        session = ThinkingPromptSession()

        async def handler(text: str) -> None:
            session.start_thinking().append("result\n")

        await session._run_handler(handler, "go")

        history = _history(session)
        assert any("result" in text for text in history)
        assert CANCELLED not in history


class TestCallbackErrors:
    """A content callback that raises is logged once, not on every redraw (#7a)."""

    def test_a_raising_callback_is_logged_once(self, caplog):
        def boom() -> str:
            raise ValueError("bad")

        control = ThinkingBoxControl(max_collapsed_lines=5)
        control.start(boom)
        with caplog.at_level(logging.ERROR, logger="thinking_prompt"):
            for _ in range(5):
                control.create_content(40, 5)
                control.get_line_count(40)

        logged = [r for r in caplog.records if "content callback" in r.getMessage()]
        assert len(logged) == 1
