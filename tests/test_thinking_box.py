"""ThinkingBox: one thinking box, and the handle start_thinking() returns and
thinking() yields."""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from unittest.mock import MagicMock

import pytest
from prompt_toolkit.keys import Keys

from thinking_prompt import ThinkingBox, ThinkingPromptSession, ThinkingPromptStyles
from thinking_prompt.frames import FrameScheduler
from tests.helpers import echoed, history_texts, keep_console, make_display, make_manager

NO_CONTENT = "shows a content callback's text"


def _session() -> ThinkingPromptSession:
    return ThinkingPromptSession(thinking_title="Pondering")


def _kept_session() -> ThinkingPromptSession:
    """A session whose Display keeps what it prints (see keep_console)."""
    session = _session()
    keep_console(session._display)
    return session


def _history(session: ThinkingPromptSession) -> list[str]:
    return history_texts(session._display)


def _ctrl_c(session: ThinkingPromptSession):
    for binding in session.app.key_bindings.bindings:
        if binding.keys == (Keys.ControlC,):
            return binding.handler
    raise AssertionError("Ctrl+C binding not registered")


class TestWriting:
    def test_append_shows_in_text(self):
        box = make_manager().create_box()
        box.append("hello")
        assert box.text == "hello"
        assert box.get_content() == "hello"

    def test_clear(self):
        box = make_manager().create_box()
        box.append("hello")
        box.clear()
        assert box.text == ""

    def test_set_line(self):
        box = make_manager().create_box()
        box.append("line0\nline1\n")
        box.set_line(-1, "REPLACED")
        assert box.text == "line0\nREPLACED\n"

    def test_set_line_rejects_text_of_more_than_one_line(self):
        box = make_manager().create_box()
        box.append("line0\n")
        with pytest.raises(ValueError, match="one line"):
            box.set_line(0, "a\nb")
        assert box.text == "line0\n"

    def test_len_counts_lines(self):
        box = make_manager().create_box()
        box.append("line0\nline1\n")
        box.append("line2")
        assert len(box) == 3

    def test_a_box_is_always_truthy(self):
        """A box is a handle, not a collection: `if box:` holds when it's empty."""
        assert bool(make_manager().create_box()) is True
        assert bool(make_manager().create_box(lambda: "")) is True


class TestTitle:
    def test_set_title_changes_the_header(self):
        box = make_manager().create_box(title="Start")
        box.set_title("Processing")
        assert box.title == "Processing"
        assert box._header.text == "Processing"

    def test_set_title_asks_for_a_redraw(self):
        calls: list[int] = []
        manager = make_manager(frames=FrameScheduler(lambda: calls.append(1)))
        box = manager.create_box(title="T")
        calls.clear()
        box.set_title("New")
        assert calls == [1]

    def test_a_box_without_a_header_has_no_title(self):
        box = make_manager().create_box()
        assert box.title == ""
        box.set_title("ignored")
        assert box.title == ""


class TestCallbackBox:
    """A box fed by a content callback can be read, not written."""

    @pytest.mark.parametrize(
        "write",
        [
            lambda box: box.append("x"),
            lambda box: box.append_rich("x"),
            lambda box: box.set_line(0, "x"),
            lambda box: box.set_line_rich(0, "x"),
            lambda box: box.clear(),
            lambda box: len(box),
        ],
    )
    def test_writes_raise_type_error_before_and_after_finish(self, write):
        box = make_manager().create_box(lambda: "shown\n")
        with pytest.raises(TypeError, match=NO_CONTENT):
            write(box)
        box.finish()
        with pytest.raises(TypeError, match=NO_CONTENT):
            write(box)

    def test_the_error_names_the_method(self):
        box = make_manager().create_box(lambda: "x")
        with pytest.raises(TypeError, match=r"^append\(\): "):
            box.append("y")

    def test_text_follows_the_callback_then_freezes_at_finish(self):
        shown = {"line": "one\n"}
        box = make_manager().create_box(lambda: shown["line"])
        assert box.text == "one\n"
        shown["line"] = "two\n"
        assert box.get_content() == "two\n"
        assert box.finish() == "two\n"
        shown["line"] = "three\n"
        assert box.text == "two\n"

    def test_a_raising_callback_reads_as_empty(self):
        def boom() -> str:
            raise ValueError("bad")

        box = make_manager().create_box(boom)
        assert box.text == ""
        assert box.finish() == ""

    def test_set_title_works(self):
        box = make_manager().create_box(lambda: "x", title="A")
        box.set_title("B")
        assert box.title == "B"


class TestFinishedBox:
    def test_finish_returns_the_text_and_text_stays_it(self):
        box = make_manager().create_box()
        box.append("hello\n")
        text = box.finish()
        assert text == "hello\n"
        assert box.text == text
        assert box.is_finished

    @pytest.mark.parametrize(
        "write",
        [
            lambda box: box.append("late\n"),
            lambda box: box.append_rich("late"),
            lambda box: box.set_line(0, "late"),
            lambda box: box.set_line_rich(0, "late"),
            lambda box: box.clear(),
            lambda box: box.set_title("late"),
        ],
    )
    def test_writes_after_finish_are_dropped(self, write):
        box = make_manager().create_box(title="T")
        box.append("kept\n")
        box.finish()
        write(box)
        assert box.text == "kept\n"
        assert box.title == "T"

    def test_a_write_that_got_past_the_finished_check_is_still_dropped(self):
        box = make_manager().create_box()
        box.append("kept\n")
        content = box._content  # what a write racing finish() already holds
        box.finish()
        content.append("late\n")
        assert content.get_content() == "kept\n"

    def test_one_warning_per_box(self, caplog):
        box = make_manager().create_box(title="T")
        box.finish()
        with caplog.at_level(logging.WARNING, logger="thinking_prompt"):
            box.append("late\n")
            box.set_line(0, "late")
            box.set_title("late")
        warnings = [r for r in caplog.records if "already finished" in r.getMessage()]
        assert len(warnings) == 1
        assert "append()" in warnings[0].getMessage()

    def test_finishing_twice_echoes_once(self):
        display = make_display()
        box = make_manager(display).create_box()
        box.append("hello\n")
        assert box.finish() == "hello\n"
        assert box.finish() == "hello\n"
        assert history_texts(display) == ["hello\n\n"]

    def test_a_write_racing_finish_is_in_the_text_or_nowhere(self):
        display = make_display()
        manager = make_manager(display)
        for _ in range(30):
            box = manager.create_box()
            stop = threading.Event()

            def write(box: ThinkingBox = box) -> None:
                i = 0
                while not stop.is_set():
                    box.append(f"{i}\n")
                    i += 1

            writer = threading.Thread(target=write)
            writer.start()
            time.sleep(0.001)
            returned = box.finish()
            time.sleep(0.001)
            stop.set()
            writer.join()

            n = returned.count("\n")
            assert returned == "".join(f"{i}\n" for i in range(n))  # no gaps
            assert box.text == returned
            if returned.strip():
                assert history_texts(display)[-1] == returned + "\n"


class TestRich:
    def test_append_rich_switches_the_box_to_ansi(self):
        pytest.importorskip("rich")
        box = make_manager().create_box()
        assert box._control.content_format == "plain"
        box.append_rich("[green]✓ Done[/green]\n")
        assert box._control.content_format == "ansi"
        assert "✓ Done" in box.text
        assert "\x1b[" in box.text

    def test_set_line_rich_switches_to_ansi_and_keeps_the_other_lines(self):
        pytest.importorskip("rich")
        box = make_manager().create_box()
        box.append("line0\nline1\n")
        box.set_line_rich(0, "[green]REPLACED[/green]")
        assert box._control.content_format == "ansi"
        assert "REPLACED" in box.text
        assert "line1" in box.text

    def test_rich_writes_use_the_sessions_theme_at_write_time(self):
        pytest.importorskip("rich")
        display = make_display()
        box = make_manager(display).create_box()
        display.set_theme(ThinkingPromptStyles(markdown_h1="red"))
        box.append_rich("[markdown.h1]x[/markdown.h1]")
        assert "\x1b[31m" in box.text

    def test_an_explicit_theme_wins(self):
        pytest.importorskip("rich")
        from rich.theme import Theme

        box = make_manager().create_box()
        box.append_rich("[accent]x[/accent]", theme=Theme({"accent": "green"}))
        assert "\x1b[32m" in box.text


class TestSessionBoxes:
    def test_start_thinking_with_a_title(self):
        assert _session().start_thinking(title="Processing").title == "Processing"

    @pytest.mark.parametrize("max_lines", [0, -1])
    def test_start_thinking_refuses_fewer_than_one_line(self, max_lines):
        """A box with no rows for its text can't be drawn: refused when made."""
        session = _session()
        with pytest.raises(ValueError, match=r"max_lines must be at least 1 \(or None\), got "):
            session.start_thinking(max_lines=max_lines)
        assert not session.is_thinking

    async def test_thinking_refuses_fewer_than_one_line(self):
        session = _session()
        with pytest.raises(ValueError, match="max_lines must be at least 1"):
            async with session.thinking(max_lines=0):
                pass
        assert not session.is_thinking

    async def test_thinking_yields_a_box_and_finishes_it(self):
        session = _session()
        async with session.thinking(
            title="Working", add_to_history=False, echo_to_console=False
        ) as box:
            assert isinstance(box, ThinkingBox)
            assert box.title == "Working"
            box.append("hello\n")
            box.set_title("Almost Done")
            assert box.title == "Almost Done"
        assert box.is_finished
        assert box.text == "hello\n"
        assert not session.is_thinking

    async def test_finishing_inside_a_thinking_block_echoes_once(self):
        session = _session()
        async with session.thinking() as box:
            box.append("done\n")
            assert box.finish() == "done\n"
        assert _history(session) == ["done\n\n"]

    async def test_a_box_finished_from_a_worker_thread(self):
        session = _session()
        box = session.start_thinking()
        box.append("from a thread\n")
        await asyncio.to_thread(box.finish)
        assert box.is_finished
        assert not session.is_thinking
        assert _history(session) == ["from a thread\n\n"]

    def test_ctrl_c_echoes_what_a_callback_box_showed(self):
        session = _session()
        session.start_thinking(lambda: "shown\n")
        _ctrl_c(session)(MagicMock())
        assert _history(session) == ["shown\n\n", "Operation cancelled...\n"]


class TestFinishArguments:
    """add_to_history and echo_to_console reach the echo, on every way out."""

    def test_finish_keeps_the_text_out_of_history_and_console_when_told_to(self):
        session = _kept_session()
        box = session.start_thinking()
        box.append("x\n")
        box.finish(add_to_history=False, echo_to_console=False)
        assert _history(session) == []
        assert echoed(session._display) == []

    def test_finish_defaults_put_the_text_in_history_and_console(self):
        """Positive control: the checks above can tell echoed from not."""
        session = _kept_session()
        box = session.start_thinking()
        box.append("x\n")
        box.finish()
        assert _history(session) == ["x\n\n"]
        assert echoed(session._display) != []

    async def test_thinking_exit_passes_the_arguments_on(self):
        session = _kept_session()
        async with session.thinking(add_to_history=False, echo_to_console=False) as box:
            box.append("x\n")
        assert _history(session) == []
        assert echoed(session._display) == []

    async def test_thinking_exit_with_an_error_passes_the_arguments_on(self):
        session = _kept_session()
        with pytest.raises(RuntimeError):
            async with session.thinking(
                add_to_history=False, echo_to_console=False
            ) as box:
                box.append("x\n")
                raise RuntimeError("boom")
        assert box.is_finished
        assert _history(session) == []
        assert echoed(session._display) == []

    async def test_thinking_exit_echoes_when_asked_to(self):
        """Positive control for the two tests above."""
        session = _kept_session()
        async with session.thinking(add_to_history=True, echo_to_console=True) as box:
            box.append("x\n")
        assert _history(session) == ["x\n\n"]
        assert echoed(session._display) != []
