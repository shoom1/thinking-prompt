"""End-to-end tests: drive a running session with piped keystrokes.

Unit tests poke the key-binding handlers directly, which misses bugs that
only appear when the real key processor, input loop and Application run
together (e.g. several keys arriving in one read). These tests run
``session.run_async()`` against a pipe input and ``DummyOutput``.
"""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Iterator
from contextlib import contextmanager
from typing import Any, Callable
from unittest.mock import patch

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import PipeInput, create_pipe_input
from prompt_toolkit.layout import BufferControl
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.widgets import TextArea

from thinking_prompt import (
    ButtonConfig,
    CheckboxField,
    ChecklistField,
    ChoiceField,
    Dialog,
    DropdownField,
    RadioField,
    SelectField,
    TextField,
    ThinkingPromptSession,
)

CTRL_A = "\x01"
CTRL_C = "\x03"
CTRL_D = "\x04"
CTRL_T = "\x14"
ENTER = "\r"
ESCAPE = "\x1b"
TAB = "\t"
SHIFT_TAB = "\x1b[Z"
DOWN = "\x1b[B"
PGUP = "\x1b[5~"
PGDN = "\x1b[6~"
UP = "\x1b[A"
RIGHT = "\x1b[C"


class _ShortOutput(DummyOutput):
    """A DummyOutput whose terminal is ``rows`` rows tall (DummyOutput: 40)
    and ``columns`` wide, with ``below_cursor`` rows free under the prompt
    if given."""

    def __init__(self, rows: int, below_cursor: int | None = None, columns: int = 80) -> None:
        super().__init__()
        self._rows = rows
        self._below_cursor = below_cursor
        self._columns = columns

    def resize(self, *, rows: int | None = None, columns: int | None = None) -> None:
        """Change the terminal's size; the next draw sees it."""
        self._rows = self._rows if rows is None else rows
        self._columns = self._columns if columns is None else columns

    def get_size(self) -> Size:
        return Size(rows=self._rows, columns=self._columns)

    def get_rows_below_cursor_position(self) -> int:
        if self._below_cursor is None:
            return super().get_rows_below_cursor_position()
        return self._below_cursor


class _RecordingOutput(_ShortOutput):
    """A _ShortOutput that keeps what's written to it, text and escapes."""

    def __init__(self, rows: int, columns: int = 80) -> None:
        super().__init__(rows, columns=columns)
        self.written: list[str] = []

    def write(self, data: str) -> None:
        self.written.append(data)

    def write_raw(self, data: str) -> None:
        self.written.append(data)

    def text(self) -> str:
        """Everything written, "\\r" dropped."""
        return "".join(self.written).replace("\r", "")


def settings_form(fields: list[Any], *, title: str = "Settings", **kwargs: Any) -> Dialog:
    """A settings form as a client builds one: the fields, then Save (every
    value) and Cancel; 60 columns wide in a box unless ``width`` says."""
    kwargs.setdefault("width", 60)
    dialog = Dialog(title, fields=fields, **kwargs)
    dialog.buttons = [
        ButtonConfig("Save", handler=lambda: dialog.set_result(dialog.values)),
        ButtonConfig("Cancel"),
    ]
    return dialog


@contextmanager
def piped_session(
    *, rows: int | None = None, below_cursor: int | None = None, columns: int = 80, **kwargs: Any
) -> Iterator[tuple[ThinkingPromptSession, PipeInput]]:
    """A session whose Application reads from a pipe and renders nowhere
    (in a ``rows``-row, ``columns`` wide terminal if given, with ``below_cursor`` rows free
    under the prompt if given)."""
    output = DummyOutput() if rows is None else _ShortOutput(rows, below_cursor, columns)
    with create_pipe_input() as inp, create_app_session(input=inp, output=output):
        yield ThinkingPromptSession(**kwargs), inp


async def wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    """Poll ``predicate`` on the event loop until it holds or time runs out."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached before timeout")
        await asyncio.sleep(0.01)


def waiting_for_input(session: ThinkingPromptSession) -> bool:
    """True when the app is up and the input loop is awaiting a line."""
    pending = session._pending_input
    return session.app.is_running and pending is not None and not pending.done()


def echoed_inputs(session: ThinkingPromptSession) -> list[str]:
    """User inputs echoed into the transcript, in order."""
    return [
        entry.fragments[1][1].rstrip("\n")
        for entry in session._display.history.iter_entries()
        if entry.kind == "formatted"
    ]


def dialog_open(session: ThinkingPromptSession) -> bool:
    dm = session._dialog_manager
    return dm is not None and dm._visible


def dialog_rendered(session: ThinkingPromptSession) -> bool:
    """The open dialog has been drawn at least once. prompt_toolkit's Tab
    navigation only considers windows visible in the last render, so send
    navigation keys (Tab/Shift-Tab) only after this holds."""
    layout = session.app.layout
    return dialog_open(session) and layout.current_window in layout.visible_windows


def inline_open(session: ThinkingPromptSession) -> bool:
    dm = session._dialog_manager
    return dm is not None and dm.inline_view is not None


def screen_lines(session: ThinkingPromptSession) -> list[str]:
    """The last rendered frame as text, one stripped string per row."""
    screen = session.app.renderer.last_rendered_screen
    if screen is None:
        return []
    # screen.width only counts columns some windows widened it to (it can
    # stay 0): read the terminal's full width.
    width = max(screen.width, session.app.output.get_size().columns)
    return [
        "".join(screen.data_buffer[y][x].char for x in range(width)).strip()
        for y in range(screen.height)
    ]


def record_dialog_frames(session: ThinkingPromptSession) -> list[list[str]]:
    """Every frame rendered while a dialog is open, from now on, as screen_lines()."""
    frames: list[list[str]] = []
    render = session.app.renderer.render

    def recording(app: Any, layout: Any, is_done: bool = False) -> None:
        render(app, layout, is_done)
        if dialog_open(session):
            frames.append(screen_lines(session))

    session.app.renderer.render = recording  # type: ignore[method-assign]
    return frames


async def first_dialog_frame(
    open_dialog: Callable[[ThinkingPromptSession], Any], **session_kwargs: Any
) -> list[str]:
    """The first frame drawn with the dialog that ``open_dialog`` opens; the
    dialog is closed with Escape afterwards."""
    closed: list[bool] = []

    async def handler(text: str) -> None:
        await open_dialog(session)
        closed.append(True)

    with piped_session(**session_kwargs) as (session, inp):
        frames = record_dialog_frames(session)

        async def script(run: asyncio.Task[None]) -> None:
            inp.send_text("go" + ENTER)
            await wait_until(lambda: len(frames) > 0)
            inp.send_text(ESCAPE)
            await wait_until(lambda: closed == [True])

        await run_with(session, handler, script)
    return frames[0]


def prompt_and_status_rows(session: ThinkingPromptSession) -> tuple[int, int]:
    """The prompt's row and the status bar's row in the last rendered frame."""
    where = session.app.renderer.last_rendered_screen.visible_windows_to_write_positions
    prompt = next(
        w for w in where
        if isinstance(w.content, BufferControl) and w.content.buffer is session.default_buffer
    )
    status = next(w for w in where if w.style == "class:status")
    return where[prompt].ypos, where[status].ypos


def inline_height(session: ThinkingPromptSession) -> int:
    """The inline dialog's rows in the last frame: between the separator
    under the prompt and the status bar."""
    prompt, status = prompt_and_status_rows(session)
    return status - prompt - 2


def cursor_row(session: ThinkingPromptSession) -> str | None:
    """The rendered row under the ❯ cursor, e.g. "❯ 1. Yes" (None if none is drawn)."""
    return next((line for line in screen_lines(session) if line.startswith("❯")), None)


async def run_with(
    session: ThinkingPromptSession,
    handler: Callable[[str], Any],
    script: Callable[[asyncio.Task[None]], Awaitable[None]],
) -> None:
    """Run the session while ``script`` drives it; always tear down."""
    run = asyncio.create_task(session.run_async(handler))
    try:
        await wait_until(lambda: waiting_for_input(session))
        await script(run)
    finally:
        if not run.done():
            session.exit()
        await asyncio.wait_for(run, timeout=2)


class TestCtrlCWithIdleBox:
    async def test_ctrl_c_clears_orphan_box_and_keeps_accepting_input(self):
        """A box left open while idle (e.g. a startup status box): Ctrl+C
        clears it, and the session keeps delivering input afterwards."""
        delivered: list[str] = []

        async def handler(text: str) -> None:
            delivered.append(text)

        with piped_session() as (session, inp):
            session.start_thinking(title="startup status")

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text(CTRL_C)
                await wait_until(lambda: not session.is_thinking)
                assert not run.done(), "Ctrl+C with an open box must not exit"
                inp.send_text("hello" + ENTER)
                await wait_until(lambda: delivered == ["hello"])

            await run_with(session, handler, script)


def history_texts(session: ThinkingPromptSession) -> list[str]:
    return [entry.text for entry in session._display.history.iter_entries()]


LONG = "\n".join(f"line {i}" for i in range(40))


class TestBoxLifecycle:
    async def test_ctrl_t_edits_the_prompt_once_the_boxes_are_gone(self):
        """Expanding a box doesn't outlive it: with no box left, Ctrl+T is
        the editor's transpose-chars again."""
        release = asyncio.Event()

        async def handler(text: str) -> None:
            async with session.thinking() as ctx:
                ctx.append(LONG)
                await release.wait()

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: session.is_thinking)
                inp.send_text(CTRL_T)
                await wait_until(lambda: session._manager.is_expanded)

                release.set()
                await wait_until(lambda: waiting_for_input(session) and not session.is_thinking)
                inp.send_text("ab")
                await wait_until(lambda: session.default_buffer.text == "ab")
                inp.send_text(CTRL_T)
                await wait_until(lambda: session.default_buffer.text == "ba")

            await run_with(session, handler, script)

    async def test_a_background_box_survives_an_unrelated_handler(self):
        """A box opened by a background task stays open when a handler
        that didn't open it ends, and finishes into history normally."""
        delivered: list[str] = []
        opened, gate = asyncio.Event(), asyncio.Event()

        def handler(text: str) -> None:
            delivered.append(text)

        async def background() -> None:
            async with session.thinking(title="Indexing") as ctx:
                ctx.append("indexed 1\n")
                opened.set()
                await gate.wait()

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                task = asyncio.create_task(background())
                await asyncio.wait_for(opened.wait(), 2)
                inp.send_text("hi" + ENTER)
                await wait_until(lambda: delivered == ["hi"] and waiting_for_input(session))
                assert session.is_thinking

                gate.set()
                await asyncio.wait_for(task, 2)
                assert not session.is_thinking
                assert any("indexed 1" in text for text in history_texts(session))

            await run_with(session, handler, script)

    async def test_ctrl_c_during_a_handler_echoes_its_box_then_says_so(self):
        async def handler(text: str) -> None:
            async with session.thinking() as ctx:
                ctx.append("working\n")
                await asyncio.sleep(3600)

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: session.is_thinking)
                inp.send_text(CTRL_C)
                await wait_until(lambda: waiting_for_input(session) and not session.is_thinking)

                history = history_texts(session)
                assert sum("working" in text for text in history) == 1
                assert history[-1] == "Operation cancelled...\n"
                assert not run.done()

            await run_with(session, handler, script)


async def settled_renders(session: ThinkingPromptSession, quiet: float = 0.15) -> int:
    """The app's render count once it hasn't redrawn for ``quiet`` seconds."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 2.0
    count, still_since = session.app.render_counter, loop.time()
    while loop.time() - still_since < quiet:
        if loop.time() > deadline:
            raise AssertionError("the app kept redrawing")
        await asyncio.sleep(0.01)
        if session.app.render_counter != count:
            count, still_since = session.app.render_counter, loop.time()
    return count


def on_screen(session: ThinkingPromptSession, text: str) -> bool:
    return any(text in line for line in screen_lines(session))


def on_frame(frame: list[str], text: str) -> bool:
    return any(text in line for line in frame)


def box_height(lines: list[str]) -> int:
    """The box dialog's rows in ``lines`` (screen_lines()): its top border to its bottom border."""
    top = next(i for i, line in enumerate(lines) if "┌" in line)
    bottom = max(i for i, line in enumerate(lines) if "┘" in line)
    return bottom - top + 1


def first_line_shown(session: ThinkingPromptSession) -> int | None:
    """The first of "line 00", "line 01", ... on screen, or None."""
    shown = [i for i in range(100) if on_screen(session, f"line {i:02}")]
    return shown[0] if shown else None


class TestRedraws:
    """The screen is redrawn when something changes or animates, never on
    a fixed timer."""

    async def test_an_idle_prompt_is_not_redrawn(self):
        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                before = await settled_renders(session)
                await asyncio.sleep(0.3)
                assert session.app.render_counter == before

            await run_with(session, lambda text: None, script)

    async def test_a_spinner_turns_while_its_box_is_open_then_redraws_stop(self):
        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                ctx = session.start_thinking(title="Working")
                headers = set()
                for _ in range(35):
                    await asyncio.sleep(0.01)
                    headers.update(line for line in screen_lines(session) if "Working" in line)
                assert len(headers) >= 2  # the spinner frame changed

                ctx.finish()
                before = await settled_renders(session)
                await asyncio.sleep(0.3)
                assert session.app.render_counter == before

            await run_with(session, lambda text: None, script)

    async def test_a_box_without_a_spinner_is_redrawn_only_when_written(self):
        with piped_session(spinner=None) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                ctx = session.start_thinking()
                before = await settled_renders(session)
                await asyncio.sleep(0.3)
                assert session.app.render_counter == before

                ctx.append("hello\n")
                await wait_until(lambda: on_screen(session, "hello"))
                ctx.set_title("Renamed")
                await wait_until(lambda: on_screen(session, "Renamed"))

            await run_with(session, lambda text: None, script)

    async def test_a_write_from_a_thread_shows(self):
        with piped_session(spinner=None) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                ctx = session.start_thinking()
                await settled_renders(session)
                writer = threading.Thread(target=ctx.append, args=("from a thread\n",))
                writer.start()
                writer.join()
                await wait_until(lambda: on_screen(session, "from a thread"))

            await run_with(session, lambda text: None, script)

    async def test_a_box_fed_by_a_callback_is_polled_while_open(self):
        chunks: list[str] = []
        with piped_session(spinner=None) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                ctx = session.start_thinking(lambda: "".join(chunks))
                await settled_renders(session, quiet=0.05)  # still polling: settles only between polls
                chunks.append("polled\n")
                await wait_until(lambda: on_screen(session, "polled"))

                ctx.finish()
                before = await settled_renders(session)
                await asyncio.sleep(0.3)
                assert session.app.render_counter == before

            await run_with(session, lambda text: None, script)

    async def test_a_status_given_as_a_callable_is_polled(self):
        shown = ["one"]
        with piped_session(status_text=lambda: shown[-1]) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                await wait_until(lambda: on_screen(session, "one"))
                shown.append("two")
                await wait_until(lambda: on_screen(session, "two"))

            await run_with(session, lambda text: None, script)

    async def test_a_prompt_message_given_as_a_callable_is_polled(self):
        shown = ["one> "]
        with piped_session(message=lambda: shown[-1]) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                await wait_until(lambda: on_screen(session, "one>"))
                shown.append("two> ")
                await wait_until(lambda: on_screen(session, "two>"))

            await run_with(session, lambda text: None, script)

    async def test_fast_writes_are_capped_at_30_redraws_a_second(self):
        with piped_session(spinner=None) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                ctx = session.start_thinking()
                before = await settled_renders(session)
                loop = asyncio.get_running_loop()
                start = loop.time()
                for i in range(60):
                    ctx.append(f"{i}\n")
                    await asyncio.sleep(0.005)
                elapsed = loop.time() - start
                renders = await settled_renders(session) - before
                assert renders <= elapsed * 30 + 3

            await run_with(session, lambda text: None, script)


class TestInputLoopLifetime:
    async def test_app_exits_when_input_loop_ends(self):
        """If the input loop stops (here: a sync handler raising
        KeyboardInterrupt), the app must exit instead of lingering as a
        zombie that echoes input nobody reads."""

        def handler(text: str) -> None:
            raise KeyboardInterrupt

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("boom" + ENTER)
                await asyncio.wait_for(asyncio.shield(run), timeout=2)

            await run_with(session, handler, script)


class TestTypeAhead:
    async def test_second_line_in_same_read_is_not_lost(self):
        """Two lines arriving in one read: the second must not be echoed
        and then dropped. It stays in the buffer until the session is ready
        for input again."""
        delivered: list[str] = []

        async def handler(text: str) -> None:
            delivered.append(text)

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("first" + ENTER + "second" + ENTER)
                await wait_until(lambda: delivered == ["first"] and waiting_for_input(session))
                assert echoed_inputs(session) == delivered
                assert session.default_buffer.text == "second"

                inp.send_text(ENTER)
                await wait_until(lambda: delivered == ["first", "second"])
                assert echoed_inputs(session) == delivered

            await run_with(session, handler, script)


class TestInputWhileBusy:
    async def test_enter_while_handler_runs_keeps_the_draft(self):
        """Enter while a handler is running is refused: the draft stays in
        the buffer (not cleared, not echoed) and can be submitted later."""
        delivered: list[str] = []
        release = asyncio.Event()

        async def handler(text: str) -> None:
            delivered.append(text)
            if text == "slow":
                await release.wait()

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("slow" + ENTER)
                await wait_until(lambda: delivered == ["slow"])
                inp.send_text("next" + ENTER)
                await asyncio.sleep(0.1)
                assert session.default_buffer.text == "next"
                assert echoed_inputs(session) == ["slow"]

                release.set()
                await wait_until(lambda: waiting_for_input(session))
                inp.send_text(ENTER)
                await wait_until(lambda: delivered == ["slow", "next"])
                assert session._input_history.get_strings()[-2:] == ["slow", "next"]

            await run_with(session, handler, script)


class TestBusyHint:
    """The "Busy" status hint is temporary: once input is accepted again the
    previous status returns — unless something set a new status meanwhile."""

    async def test_busy_hint_clears_when_input_is_accepted_again(self):
        release = asyncio.Event()

        async def handler(text: str) -> None:
            await release.wait()

        with piped_session(status_text="READY") as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("slow" + ENTER)
                await wait_until(lambda: session._current_handler_task is not None)
                inp.send_text("x" + ENTER)
                await wait_until(lambda: session.status_text == session._BUSY_STATUS)

                release.set()
                await wait_until(lambda: waiting_for_input(session))
                assert session.status_text == "READY"

            await run_with(session, handler, script)

    async def test_status_set_while_busy_is_kept(self):
        release = asyncio.Event()

        async def handler(text: str) -> None:
            await release.wait()
            session.set_status("DONE")

        with piped_session(status_text="READY") as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("slow" + ENTER)
                await wait_until(lambda: session._current_handler_task is not None)
                inp.send_text("x" + ENTER)
                await wait_until(lambda: session.status_text == session._BUSY_STATUS)

                release.set()
                await wait_until(lambda: waiting_for_input(session))
                assert session.status_text == "DONE"

            await run_with(session, handler, script)


class TestCtrlDInDialog:
    async def test_ctrl_d_in_dialog_text_field_deletes_char(self):
        """Ctrl+D while editing a dialog text field is emacs delete-char;
        it must not exit the session (the main prompt being empty is
        irrelevant when it doesn't have focus)."""
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(
                await session.show_dialog(settings_form([TextField(key="name", label="Name", default="abc")]))
            )

        with piped_session() as (session, inp):

            def editing() -> bool:
                dm = session._dialog_manager
                dialog = dm._current_dialog if dm else None
                return dialog is not None and dialog._form.controls[0].is_editing

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(ENTER)
                await wait_until(editing)
                inp.send_text(CTRL_A + CTRL_D)
                await asyncio.sleep(0.1)
                assert not run.done(), "Ctrl+D in a dialog must not exit the app"
                inp.send_text(ENTER)
                await wait_until(lambda: not editing())
                inp.send_text(TAB + ENTER)
                await wait_until(lambda: results == [{"name": "bc"}])

            await run_with(session, handler, script)

    @pytest.mark.parametrize("draft", ["", "draft"])
    async def test_ctrl_d_at_prompt_still_follows_readline_rules(self, draft: str):
        """Regression guard: at the main prompt, Ctrl+D exits only on an
        empty line."""

        async def handler(text: str) -> None:
            pass

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text(draft + CTRL_D)
                await asyncio.sleep(0.2)
                assert run.done() is (draft == "")

            await run_with(session, handler, script)


class TestDialogEscape:
    """Escape closes a dialog with its escape_result (None by default) —
    dialogs built with arguments included — unless the dialog sets escapable=False."""

    @staticmethod
    def _dialog(**kwargs: Any) -> Dialog:
        return Dialog("Pick", "Choose", [ButtonConfig("OK", result="ok")], **kwargs)

    async def test_escape_closes_dialog_with_none_by_default(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(self._dialog()))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_open(session))
                inp.send_text(ESCAPE)
                await wait_until(lambda: results == [None])

            await run_with(session, handler, script)

    async def test_not_escapable_dialog_ignores_escape(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(self._dialog(escapable=False)))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_open(session))
                inp.send_text(ESCAPE)
                await asyncio.sleep(1.0)  # past prompt_toolkit's Escape timeout
                assert results == [] and dialog_open(session)
                inp.send_text(ENTER)  # the focused OK button
                await wait_until(lambda: results == ["ok"])

            await run_with(session, handler, script)


class TestDialogsEndToEnd:
    """Dialogs driven with real keys on a running session."""

    async def test_buttonless_dialog_with_focusable_body_closes_with_escape(self):
        """No buttons is fine when the body can take focus: typing goes into
        the body (not the hidden prompt), and Escape closes the dialog."""
        from prompt_toolkit.widgets import TextArea

        results: list[Any] = []
        field = TextArea(multiline=False)

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(Dialog("Note", field)))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_open(session))
                inp.send_text("hi")
                await wait_until(lambda: field.text == "hi")
                assert session.default_buffer.text == ""
                inp.send_text(ESCAPE)
                await wait_until(lambda: results == [None])

            await run_with(session, handler, script)

    async def test_login_style_dialog_stays_open_until_input_is_valid(self):
        from prompt_toolkit.layout import HSplit
        from prompt_toolkit.widgets import Label, TextArea

        results: list[Any] = []

        async def handler(text: str) -> None:
            user = TextArea(multiline=False)

            def login() -> None:
                if user.text:
                    dlg.set_result(user.text)

            dlg = Dialog(
                "Login",
                HSplit([Label("User:"), user]),
                [ButtonConfig("Login", handler=login), ButtonConfig("Cancel")],
            )
            results.append(await session.show_dialog(dlg))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(TAB + ENTER)  # Login with the field still empty
                await asyncio.sleep(0.2)
                assert results == [] and dialog_open(session)
                inp.send_text(SHIFT_TAB + "alice" + TAB + ENTER)
                await wait_until(lambda: results == ["alice"])

            await run_with(session, handler, script)

    async def test_subclassed_login_dialog_types_into_its_field(self):
        """Pins the documented subclass pattern (README's LoginDialog):
        focus must start on the field, not a button, or typed text never
        reaches it."""
        from prompt_toolkit.layout import HSplit
        from prompt_toolkit.widgets import Label, TextArea

        class LoginDialog(Dialog):
            title = "Login"

            def __init__(self):
                super().__init__()
                self.user = TextArea(multiline=False)

            def build_body(self):
                return HSplit([Label("Username:"), self.user])

            def get_buttons(self):
                return [
                    ButtonConfig("Login", handler=self.login),
                    ButtonConfig("Cancel", handler=self.cancel),
                ]

            def login(self):
                if self.user.text:
                    self.set_result(self.user.text)

        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(LoginDialog()))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(TAB + ENTER)  # Login with the field still empty
                await asyncio.sleep(0.2)
                assert results == [] and dialog_open(session)
                inp.send_text(SHIFT_TAB + "alice" + TAB + ENTER)
                await wait_until(lambda: results == ["alice"])

            await run_with(session, handler, script)

    async def test_dropdown_dialog_returns_option_chosen_with_arrow_keys(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(
                await session.dropdown_dialog("Theme", "Pick:", ["Light", "Dark", "System"])
            )

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN + ENTER)  # "Dark": Enter presses OK
                await wait_until(lambda: results == ["Dark"])

            await run_with(session, handler, script)

    async def test_box_dropdown_starts_on_the_default(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.dropdown_dialog(
                "Theme", "Pick:", ["Light", "Dark", "System"], default="Dark"
            ))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                assert on_screen(session, "❯ Dark"), screen_lines(session)
                inp.send_text(DOWN + ENTER)  # the one after "Dark"; Enter presses OK
                await wait_until(lambda: results == ["System"])

            await run_with(session, handler, script)

    async def test_keys_pressed_before_first_render_dont_break_navigation(self):
        """Keys pressed in the instant between a dialog opening and its first
        render (typed ahead) reach the focused control, and don't break the
        dialog's Tab navigation once it's drawn. A delayed redraw makes the
        window deterministic."""
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(
                await session.dropdown_dialog("Theme", "Pick:", ["Light", "Dark", "System"])
            )

        with piped_session() as (session, inp):
            session.app.min_redraw_interval = 0.5  # render lags behind input

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_open(session))
                inp.send_text(DOWN + " ")  # pick "Dark", before the dialog's first render
                await wait_until(lambda: dialog_rendered(session), timeout=3)
                inp.send_text(TAB + ENTER)  # OK
                await wait_until(lambda: results == ["Dark"], timeout=3)

            await run_with(session, handler, script)

    async def test_escape_on_yes_no_dialog_returns_false(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.yes_no_dialog("Question", "Sure?"))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_open(session))
                inp.send_text(ESCAPE)
                await wait_until(lambda: results == [False])

            await run_with(session, handler, script)


class TestDialogsAtTheBottomOfTheTerminal:
    """With the prompt on the terminal's last rows, the app gets only the rows
    its layout asks for. A dialog shows whole on the frame it opens, without
    a key press to redraw it."""

    OPTIONS = ["Light", "Dark", "System", "High Contrast"]

    async def _first_frame(self, open_dialog: Callable[[ThinkingPromptSession], Any]) -> list[str]:
        """The first frame drawn with the dialog open, the prompt at the bottom."""
        closed: list[bool] = []

        async def handler(text: str) -> None:
            await open_dialog(session)
            closed.append(True)

        with piped_session(rows=24, below_cursor=4) as (session, inp):
            frames = record_dialog_frames(session)

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: len(frames) > 0)
                inp.send_text(ESCAPE)
                await wait_until(lambda: closed == [True])

            await run_with(session, handler, script)
        return frames[0]

    def _shows(self, frame: list[str], *texts: str) -> bool:
        return all(any(text in line for line in frame) for text in texts)

    async def test_a_box_dialog_opens_whole(self):
        frame = await self._first_frame(
            lambda s: s.dropdown_dialog("Select Theme", "Pick:", self.OPTIONS, default="System")
        )
        assert self._shows(frame, "Select Theme", *self.OPTIONS, "OK", "Cancel"), frame

    async def test_a_box_dialog_with_a_max_height_keeps_its_title(self):
        body = "\n".join(f"line {i}" for i in range(30))
        frame = await self._first_frame(
            lambda s: s.show_dialog(Dialog("Select Theme", body, [ButtonConfig("OK")], max_height=12))
        )
        assert self._shows(frame, "Select Theme", "line 0", "OK"), frame

    async def test_a_box_dialog_taller_than_the_terminal_keeps_the_layout(self):
        options = [f"Option {i}" for i in range(40)]
        frame = await self._first_frame(lambda s: s.dropdown_dialog("Select Theme", "Pick:", options))
        assert self._shows(frame, "Select Theme", ">>>", "Ctrl+C: cancel"), frame
        assert not self._shows(frame, "Window too small"), frame

    async def test_an_inline_dialog_opens_whole(self):
        frame = await self._first_frame(
            lambda s: s.dropdown_dialog(
                "Select Theme", "Pick:", self.OPTIONS, default="System", placement="inline"
            )
        )
        assert self._shows(frame, "Select Theme", *self.OPTIONS), frame


class TestBoxOverItsRoom:
    """The box sits over the rows the session reserved for it, between the
    prompt and the status bar, where an inline dialog would be; not
    centered over the whole drawn area (which covered the status bar, or
    the prompt)."""

    @staticmethod
    def _rows(session: ThinkingPromptSession) -> tuple[list[str], int, int]:
        frame = screen_lines(session)
        prompt, status = prompt_and_status_rows(session)
        return frame, prompt, status

    async def _open_at_top(self, make_dialog: Callable[[ThinkingPromptSession], Any], **terminal: Any) -> tuple[list[str], int, int]:
        """The frame with the dialog open, the prompt row and the status row."""
        closed: list[bool] = []
        seen: list[tuple[list[str], int, int]] = []

        async def handler(text: str) -> None:
            await make_dialog(session)
            closed.append(True)

        with piped_session(**terminal) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                # dialog_rendered needs a focused window; a notice has none.
                await wait_until(lambda: dialog_open(session) and any("┌" in line for line in screen_lines(session)))
                seen.append(self._rows(session))
                inp.send_text(ESCAPE)
                await wait_until(lambda: closed == [True])

            await run_with(session, handler, script)
        return seen[0]

    async def test_the_box_starts_on_the_rooms_first_row(self):
        frame, prompt, status = await self._open_at_top(
            lambda s: s.message_dialog("Hello", "Some text", placement="box"), rows=30
        )
        top = next(i for i, line in enumerate(frame) if "┌" in line)
        assert top == prompt + 2, frame  # the row after the prompt's separator
        assert max(i for i, line in enumerate(frame) if "┘" in line) < status
        assert "Ctrl+C: cancel" in frame[status], frame

    async def test_a_settings_form_leaves_the_status_bar_whole(self):
        items = [CheckboxField(key=f"s{i}", label=f"Setting {i}") for i in range(4)]
        frame, prompt, status = await self._open_at_top(
            lambda s: s.show_dialog(settings_form(items, placement="box")), rows=30
        )
        assert next(i for i, line in enumerate(frame) if "┌" in line) == prompt + 2, frame
        assert frame[status].startswith("Ctrl+C: cancel") and "│" not in frame[status], frame

    async def test_the_notice_takes_the_rooms_place_too(self):
        frame, prompt, status = await self._open_at_top(
            lambda s: s.yes_no_dialog("Delete files?", "This removes 3 files.", placement="box"),
            rows=30, columns=16,
        )
        top = next(i for i, line in enumerate(frame) if "┌" in line)
        assert top == prompt + 2, frame
        assert any("Terminal too" in line for line in frame[top:status]), frame
        assert "Ctrl+C" in frame[status] and "│" not in frame[status], frame

    async def test_a_multi_line_prompt_keeps_its_lines(self):
        """Two lines more of prompt leave a tall form fewer rows than the
        terminal less 4: it takes the rows it gets, under the prompt."""
        items = [
            CheckboxField(key=f"s{i}", label=f"Setting {i}", description=f"About {i}") for i in range(11)
        ]
        frame, _, status = await self._open_at_top(
            lambda s: s.show_dialog(settings_form(items, placement="box")),
            rows=24, message="line one\nline two\n>>> ",
        )
        last_prompt_line = next(i for i, line in enumerate(frame) if line.startswith(">>>"))
        assert next(i for i, line in enumerate(frame) if "┌" in line) == last_prompt_line + 2, frame
        for text in ("line one", "line two", ">>>"):
            (line,) = [line for line in frame if text in line]
            assert "│" not in line and "┌" not in line, frame
        assert frame[status].startswith("Ctrl+C") and "│" not in frame[status], frame

class TestBoxInASqueezedRoom:
    """When the rest of the layout takes rows from the box's (a thinking
    box), the box takes the rows it got and scrolls the rest, as an inline
    dialog does. Only rows fewer than its smallest size center it, never
    flipped over the status bar nor squeezed into "Window too small"."""

    @staticmethod
    def _form() -> list[Any]:
        return [CheckboxField(key=f"s{i}", label=f"Setting {i}") for i in range(11)]

    async def _frame_with(
        self, make_dialog: Callable[[ThinkingPromptSession], Any], *, thought_lines: int = 0, **terminal: Any
    ) -> tuple[list[str], int, int]:
        """The settled frame with the dialog open, the prompt row and the status row."""
        closed: list[bool] = []
        seen: list[tuple[list[str], int, int]] = []

        async def handler(text: str) -> None:
            if thought_lines:
                async with session.thinking() as ctx:
                    ctx.append("\n".join(f"thought {i}" for i in range(thought_lines)))
                    await make_dialog(session)
            else:
                await make_dialog(session)
            closed.append(True)

        with piped_session(**terminal) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                # A notice has no focused window, so dialog_rendered can't hold.
                await wait_until(lambda: dialog_open(session))
                await asyncio.sleep(0.3)
                seen.append((screen_lines(session), *prompt_and_status_rows(session)))
                inp.send_text(ESCAPE * 2)
                await wait_until(lambda: closed == [True])

            await run_with(session, handler, script)
        return seen[0]

    @pytest.mark.parametrize("rows", [24, 30])
    async def test_a_settings_form_shares_the_rows_with_a_thinking_box(self, rows):
        frame, prompt, status = await self._frame_with(
            lambda s: s.show_dialog(settings_form(self._form(), placement="box")),
            thought_lines=20, rows=rows,
        )
        top = next(i for i, line in enumerate(frame) if "┌" in line)
        bottom = max(i for i, line in enumerate(frame) if "┘" in line)
        assert top == prompt + 2 and bottom < status, frame
        assert frame[status].startswith("Ctrl+C"), frame
        # The thinking box keeps its newest lines in view above the prompt...
        assert any(line.startswith("thought 19") for line in frame[:prompt]), frame
        # ...and the form scrolls in the rows left to it.
        text = "\n".join(frame)
        assert "Setting 0" in text and "Setting 10" not in text, frame

    @pytest.mark.parametrize("rows", [5, 6])
    async def test_a_message_dialog_in_a_tiny_terminal_is_not_too_small(self, rows):
        frame, _, _ = await self._frame_with(
            lambda s: s.message_dialog("Hello", "Some text", placement="box"), rows=rows
        )
        assert not any("Window too sm" in line for line in frame), frame

    @pytest.mark.parametrize("rows", [7, 8, 9])
    async def test_the_status_bar_stays_whole_in_a_short_terminal(self, rows):
        frame, prompt, status = await self._frame_with(
            lambda s: s.show_dialog(settings_form(self._form()[:2], placement="box")), rows=rows
        )
        assert frame[status].startswith("Ctrl+C") and "│" not in frame[status], frame


class TestBoxMaxHeight:
    """A box dialog is no taller than its max_height and the terminal (less
    the prompt's rows); its body scrolls within that."""

    TEXT = "\n".join(f"line {i:02}" for i in range(40))

    async def test_stays_within_its_max_height(self):
        frame = await first_dialog_frame(
            lambda s: s.message_dialog("Long", self.TEXT, max_height=12, placement="box"), rows=40
        )
        assert box_height(frame) == 12
        assert on_frame(frame, "line 00") and not on_frame(frame, "line 39")

    async def test_fits_the_terminal_by_default(self):
        frame = await first_dialog_frame(
            lambda s: s.message_dialog("Long", self.TEXT, placement="box"), rows=24
        )
        assert box_height(frame) == 24 - 4

    async def test_opens_in_a_tiny_terminal(self):
        frame = await first_dialog_frame(
            lambda s: s.message_dialog("Tiny", "hello", max_height=12, placement="box"), rows=8
        )
        assert on_frame(frame, "Tiny") and on_frame(frame, "hello")

    async def test_a_width_narrower_than_its_buttons_still_shows_them(self):
        frame = await first_dialog_frame(
            lambda s: s.show_dialog(Dialog(
                "Delete files?", "This removes 3 files.",
                [ButtonConfig("Delete", result=True), ButtonConfig("Cancel", result=False)],
                width=14, placement="box",
            )),
            rows=24,
        )
        assert on_frame(frame, "This removes") and on_frame(frame, "Delete") and on_frame(frame, "Cancel"), frame

    async def test_a_settings_form_follows_the_cursor_within_its_max_height(self):
        items = [CheckboxField(key=f"s{i}", label=f"Setting {i:02}") for i in range(20)]
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(settings_form(items, title="Many", max_height=12, placement="box")))

        with piped_session(rows=40) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                assert not on_screen(session, "Setting 19")
                inp.send_text(DOWN * 19)
                await wait_until(lambda: on_screen(session, "❯ Setting 19"))
                assert box_height(screen_lines(session)) == 12
                inp.send_text(ESCAPE)
                await wait_until(lambda: results == [None])

            await run_with(session, handler, script)


class TestBoxTextScrolling:
    """A box dialog's text body scrolls with PgUp/PgDn and ↑↓ when it
    doesn't fit; the focused button keeps the focus."""

    TEXT = "\n".join(f"line {i:02}" for i in range(40))

    async def _run(self, text: str, keys_script: Callable[[ThinkingPromptSession, PipeInput], Awaitable[None]]) -> None:
        closed: list[bool] = []

        async def handler(_: str) -> None:
            await session.message_dialog("Long", text, max_height=12, placement="box")
            closed.append(True)

        with piped_session(rows=40) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                assert first_line_shown(session) == 0
                await keys_script(session, inp)
                inp.send_text(ENTER)  # OK still has the focus
                await wait_until(lambda: closed == [True])

            await run_with(session, handler, script)

    async def test_pagedown_and_pageup_page_through_the_text(self):
        async def keys(session: ThinkingPromptSession, inp: PipeInput) -> None:
            inp.send_text(PGDN)
            await wait_until(lambda: (first_line_shown(session) or 0) > 1)
            inp.send_text(PGUP)
            await wait_until(lambda: first_line_shown(session) == 0)

        await self._run(self.TEXT, keys)

    async def test_arrows_scroll_a_line(self):
        async def keys(session: ThinkingPromptSession, inp: PipeInput) -> None:
            inp.send_text(DOWN)
            await wait_until(lambda: first_line_shown(session) == 1)
            inp.send_text(UP)
            await wait_until(lambda: first_line_shown(session) == 0)

        await self._run(self.TEXT, keys)

    async def test_scrolling_stops_at_the_end(self):
        async def keys(session: ThinkingPromptSession, inp: PipeInput) -> None:
            inp.send_text(PGDN * 20)
            await wait_until(lambda: on_screen(session, "line 39"))
            first = first_line_shown(session)
            inp.send_text(DOWN)
            await asyncio.sleep(0.2)
            assert on_screen(session, "line 39") and first_line_shown(session) == first

        await self._run(self.TEXT, keys)

    async def test_keys_do_nothing_when_the_text_fits(self):
        async def keys(session: ThinkingPromptSession, inp: PipeInput) -> None:
            inp.send_text(DOWN + PGDN)
            await asyncio.sleep(0.3)
            assert first_line_shown(session) == 0

        await self._run("\n".join(f"line {i:02}" for i in range(3)), keys)

    async def test_arrows_still_move_through_a_long_list(self):
        """A body with cursor stops keeps its own ↑↓: here a choice list taller than the cap."""
        options = [f"option {i:02}" for i in range(40)]
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.dropdown_dialog(
                "Pick", "Pick one:", options, max_height=12, placement="box"
            ))

        with piped_session(rows=40) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN * 3 + ENTER)  # option 03; Enter presses OK
                await wait_until(lambda: results == ["option 03"])

            await run_with(session, handler, script)


class TestBoxLongLists:
    """A box dialog's list taller than its cap scrolls with the cursor, and
    the text above the list shows whenever the cursor is at the top."""

    async def test_a_long_dropdown_shows_its_question_at_the_top(self):
        """A choice list's question scrolls with its options, like a check
        list's: it shows at the top and again back at the first option."""
        options = [f"option {i:02}" for i in range(30)]
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.dropdown_dialog(
                "Pick", "Which one?", options, placement="box"
            ))

        with piped_session(rows=24) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                assert on_screen(session, "Which one?"), screen_lines(session)
                assert not on_screen(session, "^^")  # one scrollbar
                inp.send_text(DOWN * 29)
                await wait_until(lambda: on_screen(session, "option 29"))
                assert not on_screen(session, "Which one?")  # scrolled off
                inp.send_text(UP * 29)
                await wait_until(lambda: on_screen(session, "❯ option 00"))
                assert on_screen(session, "Which one?"), screen_lines(session)
                inp.send_text(DOWN * 3 + ENTER)  # option 03; Enter presses OK
                await wait_until(lambda: results == ["option 03"])

            await run_with(session, handler, script)

    async def test_a_long_check_list_shows_its_text_again_back_at_the_top(self):
        options = [f"option {i:02}" for i in range(20)]
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.checklist_dialog(
                "Tools", "Pick any of these", options, max_height=12, placement="box"
            ))

        with piped_session(rows=40) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                assert on_screen(session, "Pick any of these")
                inp.send_text(DOWN * 19)
                await wait_until(lambda: on_screen(session, "❯ [ ] option 19"))
                assert not on_screen(session, "Pick any of these")  # scrolled off
                inp.send_text(UP * 19)
                await wait_until(lambda: on_screen(session, "❯ [ ] option 00"))
                assert on_screen(session, "Pick any of these"), screen_lines(session)
                inp.send_text(ESCAPE)
                await wait_until(lambda: results == [None])

            await run_with(session, handler, script)


class TestInlineMaxHeight:
    """An inline dialog fits its max_height (and its text body the
    terminal); its text scrolls with PgUp/PgDn."""

    TEXT = "\n".join(f"line {i:02}" for i in range(40))

    async def _message(self, text: str, rows: int, script_body, **kwargs: Any) -> None:
        closed: list[bool] = []

        async def handler(_: str) -> None:
            await session.message_dialog("Long", text, placement="inline", **kwargs)
            closed.append(True)

        with piped_session(rows=rows) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                await wait_until(lambda: cursor_row(session) == "❯ 1. OK")
                await script_body(session, inp)
                inp.send_text(ENTER)
                await wait_until(lambda: closed == [True])

            await run_with(session, handler, script)

    async def test_stays_within_its_max_height(self):
        async def check(session: ThinkingPromptSession, inp: PipeInput) -> None:
            assert inline_height(session) == 12

        await self._message(self.TEXT, 40, check, max_height=12)

    async def test_a_text_fits_the_terminal_by_default(self):
        async def check(session: ThinkingPromptSession, inp: PipeInput) -> None:
            assert inline_height(session) <= 24 - 4
            assert first_line_shown(session) == 0

        await self._message(self.TEXT, 24, check)

    async def test_pagedown_and_pageup_page_through_the_text(self):
        async def keys(session: ThinkingPromptSession, inp: PipeInput) -> None:
            await wait_until(lambda: on_screen(session, "PgUp/PgDn scroll"))
            inp.send_text(PGDN)
            await wait_until(lambda: (first_line_shown(session) or 0) > 1)
            scrolled = first_line_shown(session)
            inp.send_text(DOWN)  # inline, ↓ is the cursor's: one action, it stays
            await asyncio.sleep(0.2)
            assert first_line_shown(session) == scrolled
            inp.send_text(PGUP)
            await wait_until(lambda: first_line_shown(session) == 0)

        await self._message(self.TEXT, 24, keys)

    async def test_a_short_terminal_takes_the_blank_rows_first(self):
        """In 8 rows, 4 for the dialog: its title, a text line, the action
        and the hint, which says the text scrolls; no blank row."""

        async def check(session: ThinkingPromptSession, inp: PipeInput) -> None:
            await settled_renders(session)
            prompt, status = prompt_and_status_rows(session)
            rows = screen_lines(session)[prompt + 2:status]
            assert rows[0] == "Long" and rows[1].startswith("line "), rows
            assert rows[-2] == "❯ 1. OK" and "PgUp/PgDn scroll" in rows[-1], rows
            assert "" not in rows, rows

        await self._message(self.TEXT, 8, check)

    async def test_the_hint_has_no_scroll_keys_when_the_text_fits(self):
        async def check(session: ThinkingPromptSession, inp: PipeInput) -> None:
            assert not on_screen(session, "PgUp/PgDn")

        await self._message("just a line", 24, check)

    async def test_a_settings_form_follows_the_cursor_within_its_max_height(self):
        items = [CheckboxField(key=f"s{i}", label=f"Setting {i:02}") for i in range(20)]
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(settings_form(items, title="Many", max_height=12, placement="inline")))

        with piped_session(rows=40) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN * 20)
                await wait_until(lambda: cursor_row(session) == "❯ 1. Save")
                assert inline_height(session) == 12
                inp.send_text(ESCAPE)
                await wait_until(lambda: results == [None])

            await run_with(session, handler, script)


class TestDialogRegrown:
    """A dialog that a shorter terminal scrolled shows the rows above its
    first stop again when rows come back, though its cursor never moved."""

    @pytest.mark.parametrize("placement,shrunk", [("inline", 7), ("box", 10)])
    async def test_the_label_above_the_picked_option_shows_again(self, placement: str, shrunk: int):
        dialog = Dialog(
            "T",
            fields=[
                RadioField("m", "Mode", options=["a", "b", "c", "d"], default="a"),
                CheckboxField("c", "Cache"),
                CheckboxField("k", "Keep"),
            ],
            placement=placement,
        )
        dialog.buttons = [ButtonConfig("OK"), ButtonConfig("Cancel")]
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session(rows=30) as (session, inp):
            session._shrinks._delay = 0.02

            def resize(rows: int) -> None:
                session.app.output.resize(rows=rows)
                session.app.invalidate()

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                await wait_until(lambda: on_screen(session, "Mode"))
                resize(shrunk)
                await wait_until(lambda: not on_screen(session, "Mode"))
                resize(14)  # back, though not in full
                await wait_until(lambda: on_screen(session, "Mode"))
                inp.send_text(ESCAPE)
                await wait_until(lambda: results == [None])

            await run_with(session, handler, script)


class TestDialogLifetime:
    """A dialog lives only as long as the app that can answer it."""

    @staticmethod
    def _dialog() -> Dialog:
        return Dialog("T", "B", [ButtonConfig("OK", result="ok")])

    async def test_app_exit_cancels_a_dialog_opened_outside_the_handler(self):
        """A dialog awaited by the input handler is cancelled with it on exit.
        One opened from another task used to wait forever once the app
        exited, and the manager kept it, refusing every later dialog."""
        background: list[asyncio.Future[Any]] = []

        def handler(text: str) -> None:
            background.append(asyncio.ensure_future(session.show_dialog(self._dialog())))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_open(session))
                session.exit()
                await asyncio.wait_for(run, timeout=2)

            await run_with(session, handler, script)

            (task,) = background
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)
            assert session._dialogs._current_dialog is None

    async def test_show_dialog_after_exit_raises(self):
        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                session.exit()
                await asyncio.wait_for(run, timeout=2)

            await run_with(session, lambda text: None, script)

            with pytest.raises(RuntimeError, match="needs a running session"):
                await asyncio.wait_for(session.show_dialog(self._dialog()), timeout=1)


class TestInlineDialogs:
    """Inline dialogs: rows between the prompt and the status bar."""

    @staticmethod
    def _dialog(**kwargs: Any) -> Dialog:
        return Dialog(
            "Delete 3 files?",
            "This can't be undone.",
            [ButtonConfig("Delete", result="delete"), ButtonConfig("Keep", result="keep")],
            placement="inline",
            **kwargs,
        )

    async def test_no_padding_when_the_layout_has_spare_height(self):
        """Regression: _AtMost used to let HSplit distribute spare layout
        height to the inline dialog, padding it with blank rows up to
        MAX_ROWS instead of sizing to its actual content (in any render
        with rows to spare)."""
        from prompt_toolkit.layout import Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.layout.layout import walk

        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(self._dialog()))

        # Every row under the prompt free: the layout gets the 40 rows the
        # dialog doesn't fill.
        with piped_session(rows=40, below_cursor=40) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                where = session.app.renderer.last_rendered_screen.visible_windows_to_write_positions
                view = session._dialog_manager.inline_view
                text_windows = [
                    c for c in walk(view.container)
                    if isinstance(c, Window) and isinstance(c.content, FormattedTextControl)
                ]
                hint_window = text_windows[-1]  # title, body, ..., hint: hint is last
                last_action = view.actions[-1].window
                # One blank spacer row, then the hint, directly below the
                # last action's one row — not padded out toward MAX_ROWS.
                assert where[hint_window].ypos == where[last_action].ypos + 2
                inp.send_text(ENTER)
                await wait_until(lambda: results == ["delete"])

            await run_with(session, handler, script)

    async def test_drawn_below_the_prompt_and_above_the_status_bar(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(self._dialog()))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                where = session.app.renderer.last_rendered_screen.visible_windows_to_write_positions
                prompt = next(
                    w for w in where
                    if isinstance(w.content, BufferControl) and w.content.buffer is session.default_buffer
                )
                status = next(w for w in where if w.style == "class:status")
                action = session._dialog_manager.inline_view.actions[0].window
                assert where[prompt].ypos < where[action].ypos < where[status].ypos
                inp.send_text(ENTER)
                await wait_until(lambda: results == ["delete"])

            await run_with(session, handler, script)

    async def test_arrows_and_enter_choose_an_action(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(self._dialog()))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN + ENTER)
                await wait_until(lambda: results == ["keep"])

            await run_with(session, handler, script)

    async def test_a_digit_chooses_directly(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(self._dialog()))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text("2")
                await wait_until(lambda: results == ["keep"])

            await run_with(session, handler, script)

    async def test_escape_closes_an_escapable_dialog(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(self._dialog()))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(ESCAPE)
                await wait_until(lambda: results == [None])

            await run_with(session, handler, script)

    async def test_escape_is_ignored_when_not_escapable(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(self._dialog(escapable=False)))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(ESCAPE)
                await asyncio.sleep(1.0)  # past prompt_toolkit's Escape timeout
                assert results == [] and inline_open(session)
                inp.send_text(ENTER)
                await wait_until(lambda: results == ["delete"])

            await run_with(session, handler, script)

    async def test_typing_does_not_reach_the_prompt_and_focus_returns(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(self._dialog()))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text("x")
                await asyncio.sleep(0.1)
                assert session.default_buffer.text == ""
                inp.send_text(ENTER)
                await wait_until(lambda: results == ["delete"])
                # Keys are handled in order: "x" was handled before Enter.
                assert session.default_buffer.text == ""
                assert not inline_open(session)
                assert session.app.layout.has_focus(session.default_buffer)

            await run_with(session, handler, script)

    async def test_session_default_placement_applies(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            dialog = Dialog("Go?", "", [ButtonConfig("Yes", result="yes")])
            results.append(await session.show_dialog(dialog))

        with piped_session(dialog_placement="inline") as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: inline_open(session) and dialog_rendered(session))
                inp.send_text(ENTER)
                await wait_until(lambda: results == ["yes"])

            await run_with(session, handler, script)

    async def test_text_field_body_keeps_its_keys_and_tab_reaches_the_actions(self):
        from prompt_toolkit.widgets import TextArea

        results: list[Any] = []
        field = TextArea(multiline=False)

        async def handler(text: str) -> None:
            def submit() -> None:
                dialog.set_result(field.text)

            dialog = Dialog(
                "Name", field, [ButtonConfig("Submit", handler=submit), ButtonConfig("Cancel")],
                placement="inline",
            )
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text("a1")  # a digit types into the field, not "run action 1"
                await wait_until(lambda: field.text == "a1")
                inp.send_text(TAB + ENTER)  # Tab to "1. Submit"
                await wait_until(lambda: results == ["a1"])

            await run_with(session, handler, script)

    async def test_ctrl_c_cancels_the_handler_and_closes_the_dialog(self):
        async def handler(text: str) -> None:
            await session.show_dialog(self._dialog())

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(CTRL_C)
                await wait_until(lambda: not dialog_open(session) and waiting_for_input(session))
                assert not inline_open(session)

            await run_with(session, handler, script)

    async def test_app_exit_cancels_an_inline_dialog(self):
        background: list[asyncio.Future[Any]] = []

        def handler(text: str) -> None:
            background.append(asyncio.ensure_future(session.show_dialog(self._dialog())))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: inline_open(session))
                session.exit()
                await asyncio.wait_for(run, timeout=2)

            await run_with(session, handler, script)

            (task,) = background
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)
            assert not inline_open(session)

    async def test_inline_dropdown_starts_on_the_default(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.dropdown_dialog(
                "Theme", "Pick:", ["Light", "Dark", "System"], default="Dark", placement="inline"
            ))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN + ENTER)
                await wait_until(lambda: results == ["System"])

            await run_with(session, handler, script)

    async def test_long_inline_list_scrolls_with_the_cursor(self):
        from thinking_prompt.dialog_inline import MAX_ROWS

        options = [f"option {i}" for i in range(1, 31)]
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.dropdown_dialog("Pick", "", options, placement="inline"))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                target = session._dialog_manager.inline_view.actions[20].window
                inp.send_text(DOWN * 20)
                await wait_until(lambda: session.app.layout.has_focus(target))

                # ScrollablePane copies every child window's write position into
                # the real screen, scrolled-off ones included (at an adjusted
                # ypos) — so target merely being in visible_windows doesn't mean
                # the pane has scrolled to it yet in the last rendered frame.
                # Wait for the rendered positions themselves to show the
                # cursor row between the prompt and the status bar.
                found: dict[str, Any] = {}

                def scrolled() -> bool:
                    where = session.app.renderer.last_rendered_screen.visible_windows_to_write_positions
                    prompt = next(
                        (w for w in where
                         if isinstance(w.content, BufferControl)
                         and w.content.buffer is session.default_buffer),
                        None,
                    )
                    status = next((w for w in where if w.style == "class:status"), None)
                    if prompt is None or status is None or target not in where:
                        return False
                    if not (where[prompt].ypos < where[target].ypos < where[status].ypos):
                        return False
                    found["where"], found["prompt"], found["status"] = where, prompt, status
                    return True

                await wait_until(scrolled, timeout=3.0)
                where, prompt, status = found["where"], found["prompt"], found["status"]
                # The dialog stays small: title, separator, at most MAX_ROWS
                # rows, blank, hint.
                assert where[status].ypos - where[prompt].ypos <= MAX_ROWS + 5
                inp.send_text(ENTER)
                await wait_until(lambda: results == ["option 21"])

            await run_with(session, handler, script)

    async def test_a_long_text_body_is_drawn_in_full(self):
        """A text body has no cursor stops: it's drawn above the scrolling
        region, and when it fits the terminal it's drawn in full (not cut to
        MAX_ROWS); the actions below it stay reachable."""
        body = [f"body line {i}" for i in range(1, 21)]
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.yes_no_dialog(
                "Delete?", "\n".join(body), placement="inline"
            ))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                await wait_until(lambda: cursor_row(session) == "❯ 1. Yes")
                prompt, status = prompt_and_status_rows(session)
                between = screen_lines(session)[prompt + 1:status]
                assert body[0] in between and body[-1] in between, between
                start = between.index(body[0])
                assert between[start:start + len(body)] == body
                inp.send_text(DOWN + ENTER)  # 2. No
                await wait_until(lambda: results == [False])

            await run_with(session, handler, script)

    async def test_a_short_terminal_still_draws_the_cursor_row(self):
        """In an 8-row terminal the dialog is squeezed: the blank rows give
        way, but the scrolling region keeps one row, the cursor row."""
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.yes_no_dialog(
                "Delete?", "3 files", placement="inline"
            ))

        with piped_session(rows=8) as (session, inp):

            def cursor_drawn(row: str) -> bool:
                lines = screen_lines(session)
                if row not in lines:
                    return False
                prompt, status = prompt_and_status_rows(session)
                return prompt < lines.index(row) < status

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                await wait_until(lambda: "Delete?" in screen_lines(session))
                assert cursor_drawn("❯ 1. Yes"), screen_lines(session)
                inp.send_text(DOWN)
                await wait_until(lambda: cursor_drawn("❯ 2. No"))
                inp.send_text(ENTER)
                await wait_until(lambda: results == [False])

            await run_with(session, handler, script)

    async def test_a_tall_text_field_scrolls_with_its_own_cursor(self):
        """A text field taller than the region, as the first stop: moving
        its text cursor up doesn't pull the region back toward its top
        (which kept the cursor pinned to the bottom row)."""
        from prompt_toolkit.widgets import TextArea

        field = TextArea(text="\n".join(f"line {i}" for i in range(1, 31)))
        field.buffer.cursor_position = field.document.translate_row_col_to_index(19, 0)
        results: list[Any] = []

        async def handler(text: str) -> None:
            dialog = Dialog("Notes", field, [ButtonConfig("OK", result="ok")], placement="inline")
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            def text_cursor_on(line: str) -> int | None:
                """The text cursor's rendered row, if it's on ``line``."""
                screen = session.app.renderer.last_rendered_screen
                point = screen.cursor_positions.get(field.window) if screen else None
                lines = screen_lines(session)
                if point is None or point.y >= len(lines) or lines[point.y] != line:
                    return None
                prompt, status = prompt_and_status_rows(session)
                return point.y if prompt < point.y < status else None

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                await wait_until(lambda: text_cursor_on("line 20") is not None)
                bottom = text_cursor_on("line 20")  # opened: line 20 on the region's last row
                inp.send_text(UP * 3)
                await wait_until(lambda: text_cursor_on("line 17") is not None)
                assert text_cursor_on("line 17") == bottom - 3, screen_lines(session)
                inp.send_text(TAB + ENTER)  # 1. OK
                await wait_until(lambda: results == ["ok"])

            await run_with(session, handler, script)

    async def test_back_on_the_first_option_the_text_above_it_shows_again(self):
        """A check list's text scrolls with its options; returning to the
        first option scrolls the region back to its top."""
        options = [f"option {i}" for i in range(1, 15)]
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.checklist_dialog(
                "Tools", "Pick any of these\nor none at all", options, placement="inline"
            ))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN * 13)
                await wait_until(lambda: cursor_row(session) == "❯ [ ] option 14")
                assert "Pick any of these" not in screen_lines(session)  # scrolled off
                inp.send_text(UP * 13)
                await wait_until(lambda: cursor_row(session) == "❯ [ ] option 1")
                lines = screen_lines(session)
                prompt, status = prompt_and_status_rows(session)
                first_option = lines.index("❯ [ ] option 1")
                assert prompt < first_option < status
                above = lines[prompt + 1:first_option]
                assert above[-2:] == ["Pick any of these", "or none at all"], above
                inp.send_text(" " + "1")  # check option 1, then 1. OK
                await wait_until(lambda: results == [["option 1"]])

            await run_with(session, handler, script)


class TestInlineSettings:
    """The settings dialog inline: settings rows, then Save / Cancel, one cursor."""

    async def test_values_sit_after_their_labels_in_a_wide_terminal(self):
        items = [
            CheckboxField(key="stream", label="Stream", default=True),
            TextField(key="name", label="Name", default="bob"),
        ]
        frame = await first_dialog_frame(
            lambda s: s.show_dialog(settings_form(items, placement="inline")),
            rows=24, columns=120,
        )
        stream = next(line for line in frame if "Stream" in line)
        name = next(line for line in frame if "Name" in line)
        assert stream.index("true") - stream.index("Stream") == len("Stream") + 2
        assert name.index("bob") - name.index("Name") == len("Stream") + 2

    @pytest.mark.parametrize("placement", ["inline", "box"])
    async def test_descriptions_end_before_the_values(self, placement):
        items = [
            DropdownField(
                key="theme", label="Theme", description="Application color scheme",
                options=["Light", "System"], default="System", width=20,
            ),
            TextField(key="name", label="Username", description="Your display name", default="Guest", edit_width=20),
            CheckboxField(
                key="notify", label="Enable Notifications", description="Show desktop notifications", default=True,
            ),
        ]
        frame = await first_dialog_frame(
            lambda s: s.show_dialog(settings_form(items, placement=placement)),
            rows=24, columns=100,
        )
        # Descriptions start where labels do: each ends two columns short
        # of the values, at least.
        row = next(line for line in frame if "Username" in line)
        label_to_value = row.index("Guest") - row.index("Username")
        for description in ("Application color scheme", "Your display name", "Show desktop notifications"):
            assert len(description) + 2 <= label_to_value, (description, frame)

    @pytest.mark.parametrize("align", ["labels", "right"])
    async def test_a_narrow_terminal_cuts_labels_and_keeps_every_value(self, align):
        items = [
            CheckboxField(key="stream", label="Stream responses", default=True),
            DropdownField(key="model", label="Model for summaries", options=["gpt-4o", "o1"], default="o1"),
            TextField(key="name", label="Display name", default="bob"),
        ]
        frame = await first_dialog_frame(
            lambda s: s.show_dialog(settings_form(items, placement="inline", align_values=align)),
            rows=24, columns=24,
        )
        rows = {
            value: next(line.strip().lstrip("❯ ") for line in frame if line.strip().lstrip("❯ ").startswith(label))
            for label, value in (("Stream", "true"), ("Mo", "o1"), ("Dis", "bob"))
        }
        for value, row in rows.items():
            assert value in row, row
            label = row[: row.index(value)].replace("◀", "").strip()
            assert label.endswith("…"), row  # cut where it didn't fit
            assert len(label) >= 3, row  # and never below 3 columns

    @staticmethod
    def _items() -> list[Any]:
        return [
            SelectField(key="model", label="Model", options=["a", "b", "c"], default="a"),
            CheckboxField(key="stream", label="Stream", default=False),
            TextField(key="name", label="Name", default=""),
        ]

    @staticmethod
    def _editing(session: ThinkingPromptSession) -> bool:
        dm = session._dialog_manager
        dialog = dm._current_dialog if dm else None
        return dialog is not None and dialog._is_editing()

    async def test_one_cursor_walks_the_settings_then_the_actions(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(settings_form(self._items(), placement="inline")))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(RIGHT)           # Model: a -> b
                inp.send_text(DOWN + " ")      # Stream: on
                inp.send_text(DOWN + ENTER)    # Name: start editing
                await wait_until(lambda: self._editing(session))
                inp.send_text("bob" + ENTER)   # confirm
                await wait_until(lambda: not self._editing(session))
                inp.send_text(DOWN + ENTER)    # 1. Save
                await wait_until(
                    lambda: results == [{"model": "b", "stream": True, "name": "bob"}]
                )

            await run_with(session, handler, script)

    @staticmethod
    def _with_dropdown() -> Dialog:
        """An inline form: a dropdown (b of a-d) and a checkbox; Save returns the values."""
        return settings_form(
            [
                DropdownField("model", "Model", options=["a", "b", "c", "d"], default="b"),
                CheckboxField("stream", "Stream"),
            ],
            placement="inline",
        )

    async def test_a_dropdown_opens_its_menu_and_enter_keeps_the_choice(self):
        dialog = self._with_dropdown()
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(ENTER)                 # open the menu
                await wait_until(lambda: on_screen(session, "│d"))
                inp.send_text(DOWN + ENTER)          # c
                await wait_until(lambda: not on_screen(session, "│d"))
                inp.send_text(DOWN + DOWN + ENTER)   # Stream, then 1. Save
                await wait_until(lambda: results == [{"model": "c", "stream": False}])

            await run_with(session, handler, script)

    async def test_escape_with_the_menu_open_closes_only_the_menu(self):
        dialog = self._with_dropdown()
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(ENTER + DOWN)          # open the menu, on c
                await wait_until(lambda: on_screen(session, "│d"))
                inp.send_text(ESCAPE)                # b again; the dialog stays
                await wait_until(lambda: not on_screen(session, "│d"))
                assert results == [] and dialog_rendered(session)
                inp.send_text(DOWN + DOWN + ENTER)   # Stream, then 1. Save
                await wait_until(lambda: results == [{"model": "b", "stream": False}])

            await run_with(session, handler, script)

    @pytest.mark.parametrize("key", [TAB, SHIFT_TAB, "1"], ids=["tab", "shift-tab", "digit"])
    async def test_keys_with_the_menu_open_stay_in_the_menu(self, key):
        """Not the dialog's: a Tab, Shift+Tab or digit that got out would move
        the cursor (a row either way) or run an action, and the keys after
        it would act elsewhere."""
        dialog = settings_form(
            [
                CheckboxField("cache", "Cache"),
                DropdownField("model", "Model", options=["a", "b", "c", "d"], default="b"),
                CheckboxField("stream", "Stream"),
            ],
            placement="inline",
        )
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN + ENTER)          # Model: open the menu
                await wait_until(lambda: on_screen(session, "│d"))
                inp.send_text(key)
                inp.send_text(DOWN + ENTER)          # c
                inp.send_text(DOWN + DOWN + ENTER)   # Stream, then 1. Save
                await wait_until(lambda: results == [{"cache": False, "model": "c", "stream": False}])

            await run_with(session, handler, script)

    async def test_a_dialog_that_fails_to_open_leaves_no_menu_behind(self):
        dialog = self._with_dropdown()
        failed: list[Exception] = []

        async def handler(text: str) -> None:
            try:
                await session.show_dialog(dialog)
            except ValueError as exc:
                failed.append(exc)

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                layout = session.app.layout
                focus = layout.focus

                def refuse_the_dialog(target: Any) -> None:
                    layout.focus = focus  # type: ignore[method-assign]
                    raise ValueError("can't focus")

                layout.focus = refuse_the_dialog  # type: ignore[method-assign]
                inp.send_text("go" + ENTER)
                await wait_until(lambda: failed)
                row = dialog._form.controls[0]._window
                assert not any(f.attach_to_window is row for f in layout.container.floats)
                assert session._dialog_manager.inline_view is None

            await run_with(session, handler, script)

    async def test_the_menu_goes_with_the_dialog(self):
        dialog = self._with_dropdown()
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            def menus() -> list[Any]:
                """The dropdown's menu floats on the session's float layer."""
                row = dialog._form.controls[0]._window
                return [f for f in session.app.layout.container.floats if f.attach_to_window is row]

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(ENTER + DOWN)          # open the menu, on c
                await wait_until(lambda: on_screen(session, "│d"))
                assert len(menus()) == 1
                dialog.cancel()                      # closed with the menu open
                await wait_until(lambda: results == [None])
                assert menus() == []
                inp.send_text("go" + ENTER)          # shown again: b, no menu
                await wait_until(lambda: dialog_rendered(session))
                assert not on_screen(session, "│d")
                assert dialog.values == {"model": "b", "stream": False}
                inp.send_text(ESCAPE)
                await wait_until(lambda: results == [None, None])

            await run_with(session, handler, script)

    async def test_escape_while_editing_text_only_ends_the_edit(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(settings_form(self._items(), placement="inline")))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN + DOWN + ENTER)
                await wait_until(lambda: self._editing(session))
                inp.send_text("x" + ESCAPE)
                await wait_until(lambda: not self._editing(session), timeout=3)
                await asyncio.sleep(0.2)
                assert results == [] and inline_open(session)
                inp.send_text(ESCAPE)  # now it closes the dialog
                await wait_until(lambda: results == [None], timeout=3)

            await run_with(session, handler, script)

    async def test_no_settings_just_the_actions(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(settings_form([], placement="inline")))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(ENTER)  # 1. Save
                await wait_until(lambda: results == [{}])

            await run_with(session, handler, script)

    async def test_box_settings_still_walk_with_arrows_and_tab_to_the_buttons(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(settings_form(self._items())))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(RIGHT + DOWN + " ")  # Model: b; Stream: on
                inp.send_text(TAB + TAB + ENTER)   # Name, then the Save button
                await wait_until(lambda: results == [{"model": "b", "stream": True, "name": ""}])

            await run_with(session, handler, script)

    async def test_box_settings_shift_tab_at_the_first_setting_stays_put(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(settings_form(self._items())))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                # Still on Model after Shift+Tab (not wrapped to the buttons): → changes it.
                inp.send_text(SHIFT_TAB + RIGHT + TAB * 3 + ENTER)  # Model, then Stream, Name and Save
                await wait_until(lambda: results == [{"model": "b", "stream": False, "name": ""}])

            await run_with(session, handler, script)

    async def test_box_settings_tab_from_the_last_check_list_option_reaches_the_buttons(self):
        results: list[Any] = []
        items = [
            CheckboxField(key="stream", label="Stream", default=False),
            ChecklistField(key="tools", label="Tools", options=["search", "code"], default=("search",)),
        ]

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(settings_form(items)))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN + DOWN + " ")  # the last option: check "code"
                inp.send_text(TAB + ENTER)        # on to the Save button
                await wait_until(lambda: results == [{"stream": False, "tools": ["search", "code"]}])

            await run_with(session, handler, script)

    async def test_check_and_radio_lists_one_option_per_line(self):
        results: list[Any] = []
        items = [
            ChecklistField(key="tools", label="Tools", options=["search", "code"], default=("search",)),
            RadioField(key="mode", label="Mode", options=["fast", "careful"], default="fast"),
        ]

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(settings_form(items, placement="inline")))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                # Stops: search, code, fast, careful, Save, Cancel
                inp.send_text(DOWN + " ")         # check "code"
                inp.send_text(DOWN + DOWN + " ")  # pick "careful"
                inp.send_text(DOWN + ENTER)       # 1. Save
                await wait_until(
                    lambda: results == [{"tools": ["search", "code"], "mode": "careful"}]
                )

            await run_with(session, handler, script)


class TestSettingsInANarrowBox:
    """At a value column too wide for a box's rows, values end at the rows'
    right edge, and a text field being edited sits where its value was."""

    async def test_editing_text_keeps_the_form_and_the_field_where_the_value_was(self):
        items = [
            TextField(key="name", label="Name", default="bob"),
            CheckboxField(key="stream", label="Stream"),
        ]
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(settings_form(items, width=40, align_values=30, placement="box")))

        def from_the_right(text: str) -> int:
            """How far from the end of its row ``text`` starts."""
            line = next(line for line in screen_lines(session) if text in line)
            return len(line) - line.index(text)

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                shown = from_the_right("bob")
                inp.send_text(ENTER)
                await wait_until(lambda: TestInlineSettings._editing(session))
                await settled_renders(session)
                assert on_screen(session, "Stream") and on_screen(session, "Save"), screen_lines(session)
                assert from_the_right("bob") == shown
                inp.send_text("by" + ENTER)
                await wait_until(lambda: not TestInlineSettings._editing(session))
                inp.send_text(TAB * 2 + ENTER)  # Stream, then Save
                await wait_until(lambda: results == [{"name": "bobby", "stream": False}])

            await run_with(session, handler, script)


class TestBoxTooSmall:
    """A box dialog whose smallest size doesn't fit the terminal draws a
    notice in its place; the dialog stays open, with its keys."""

    ITEMS = [
        CheckboxField(key="s", label="Stream responses", default=True),
        DropdownField(key="m", label="Model for summaries", options=["gpt-4o", "o1"], default="o1"),
        TextField(key="n", label="Display name", default="bob"),
    ]

    @staticmethod
    def _text(frame: list[str]) -> str:
        """The frame's words, rows joined, so a wrapped notice reads as one line."""
        return " ".join(line.strip("│┌└┐┘─| ").strip() for line in frame)

    async def _ask(self, make_dialog: Callable[[ThinkingPromptSession], Any], script_keys: Callable[..., Awaitable[None]], **terminal: Any) -> Any:
        """Open the dialog ``make_dialog`` makes, in a terminal as ``terminal``
        says; ``script_keys(session, inp, frames)`` runs once it's drawn."""
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await make_dialog(session))

        with piped_session(**terminal) as (session, inp):
            frames = record_dialog_frames(session)

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: len(frames) > 0)
                await script_keys(session, inp, frames)
                await wait_until(lambda: len(results) == 1)

            await run_with(session, handler, script)
        return results[0]

    @staticmethod
    def _yes_no(session: ThinkingPromptSession) -> Any:
        return session.yes_no_dialog("Delete files?", "This removes 3 files.", placement="box")

    async def test_a_narrow_terminal_shows_the_notice_not_the_collapsed_box(self):
        shown: list[list[str]] = []

        async def keys(session, inp, frames):
            shown.append(frames[0])
            inp.send_text(ESCAPE)

        await self._ask(self._yes_no, keys, rows=24, columns=16)
        text = self._text(shown[0])
        assert "too small" in text and "27" in text and "Esc cancels" in text, shown[0]
        assert "Delete" in text  # the title, clipped to the frame

    async def test_escape_cancels_under_the_notice(self):
        async def keys(session, inp, frames):
            inp.send_text(ESCAPE)

        assert await self._ask(self._yes_no, keys, rows=24, columns=16) is False

    async def test_enter_presses_the_focused_button_under_the_notice(self):
        async def keys(session, inp, frames):
            inp.send_text(ENTER)

        assert await self._ask(self._yes_no, keys, rows=24, columns=16) is True

    async def test_the_dialog_stays_in_the_layout_under_the_notice(self):
        """Tab and Left/Right between buttons only act on windows drawn, so
        under the notice they do nothing. But the Dialog's own bindings and
        its modality (a modal container above the button) are found through the layout's parent relations, which
        must still reach the dialog from the focused button."""
        found: list[bool] = []

        async def keys(session, inp, frames):
            assert "too small" in self._text(frames[0])
            layout = session.app.layout
            button = session._dialog_manager._box.view.buttons[0].window
            parents = []
            node = layout.get_parent(button)
            while node is not None:
                parents.append(node)
                node = layout.get_parent(node)
            found.append(any(p.is_modal() for p in parents))
            inp.send_text(ESCAPE)

        await self._ask(self._yes_no, keys, rows=24, columns=16)
        assert found == [True]

    async def test_a_dialog_that_ignores_escape_does_not_say_escape_cancels(self):
        shown: list[list[str]] = []

        def make(session):
            return session.show_dialog(Dialog("Sure?", "Really?", [ButtonConfig("Yes", result=1)], escapable=False))

        async def keys(session, inp, frames):
            shown.append(frames[0])
            inp.send_text(ENTER)

        await self._ask(make, keys, rows=24, columns=10)
        assert "too small" in self._text(shown[0]) and "Esc" not in self._text(shown[0])

    async def test_a_short_terminal_shows_the_notice(self):
        shown: list[list[str]] = []

        def make(session):
            return session.message_dialog("Note", "Saved.\nAll done.", placement="box")

        async def keys(session, inp, frames):
            shown.append(frames[0])
            inp.send_text(ESCAPE)

        await self._ask(make, keys, rows=3, columns=80)
        text = self._text(shown[0])
        assert "too small" in text and "×4" in text, shown[0]
        assert "Saved." not in text and "OK" not in text

    async def test_growing_the_terminal_brings_the_box_back(self):
        grown: list[list[str]] = []

        async def keys(session, inp, frames):
            assert "too small" in self._text(frames[0])
            session.app.output.resize(columns=80)
            session.app.invalidate()
            await wait_until(lambda: on_screen(session, "Yes"))
            grown.append(screen_lines(session))
            inp.send_text(ENTER)

        assert await self._ask(self._yes_no, keys, rows=24, columns=16) is True
        text = self._text(grown[0])
        assert "This removes 3 files." in text and "Yes" in text and "No" in text
        assert "too small" not in text

    async def test_a_settings_form_in_a_narrow_box_shows_the_notice_then_fits_at_40(self):
        for cols, small in [(24, True), (40, False)]:
            frame = await first_dialog_frame(
                lambda s: s.show_dialog(settings_form(self.ITEMS, placement="box")),
                rows=14, columns=cols,
            )
            text = self._text(frame)
            assert ("too small" in text) is small, frame
            if not small:
                assert "Stream responses" in text and "Save" in text and "Cancel" in text


class TestChecklistDialog:
    async def test_inline(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.checklist_dialog(
                "Tools", "Pick any", ["search", "code", "files"], defaults=["search"],
                placement="inline",
            ))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                # Stops: search, code, files, OK, Cancel
                inp.send_text(" " + DOWN + " ")  # uncheck search, check code
                inp.send_text(DOWN + DOWN + ENTER)  # 1. OK
                await wait_until(lambda: results == [["code"]])

            await run_with(session, handler, script)

    async def test_box(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.checklist_dialog(
                "Tools", "Pick any", ["search", "code", "files"], defaults=["search"]
            ))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(" " + DOWN + " ")  # uncheck search, check code
                inp.send_text(TAB + ENTER)  # Tab leaves the list: the OK button
                await wait_until(lambda: results == [["code"]])

            await run_with(session, handler, script)


class TestBoxDropdownMenu:
    """A box dropdown's menu opens under its own row and uses the terminal's room."""

    @staticmethod
    def _items() -> list[Any]:
        return [
            CheckboxField(key="a", label="Stream"),
            CheckboxField(key="b", label="Verbose"),
            DropdownField(key="d", label="Model", options=["alpha", "beta", "gamma"], default="beta"),
            CheckboxField(key="c", label="Cache"),
            CheckboxField(key="e", label="Echo"),
            CheckboxField(key="f", label="Fast"),
            CheckboxField(key="g", label="Debug"),
        ]

    @pytest.mark.parametrize("align", ["labels", "right"])
    async def test_the_menu_opens_under_its_own_row_showing_every_option(self, align):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(settings_form(self._items(), placement="box", align_values=align)))

        with piped_session(rows=30) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN * 2 + ENTER)
                await wait_until(lambda: on_screen(session, "alpha"))
                lines = screen_lines(session)
                (row,) = [i for i, line in enumerate(lines) if "❯ Model" in line]
                assert "beta" in lines[row]  # its row isn't covered
                assert "┌" in lines[row + 1]
                value = lines[row].index("beta")
                top = lines[row + 1]
                assert top.index("┌") <= value < top.index("┐")  # under the value
                menu = "\n".join(lines[row + 2:row + 5])
                assert [name in menu for name in ("alpha", "beta", "gamma")] == [True] * 3
                assert "└" in lines[row + 5]
                inp.send_text(DOWN + ENTER)  # gamma
                await wait_until(lambda: not on_screen(session, "alpha"))
                inp.send_text(TAB * 5 + ENTER)  # from Model through c, e, f, g to Save
                await wait_until(lambda: results == [{
                    "a": False, "b": False, "d": "gamma", "c": False, "e": False, "f": False, "g": False,
                }])

            await run_with(session, handler, script)

    async def test_a_menu_with_more_options_than_fit_scrolls_and_picks_the_right_one(self):
        options = [f"opt{i}" for i in range(10)]
        items = [
            CheckboxField(key="a", label="Stream"),
            CheckboxField(key="b", label="Verbose"),
            DropdownField(key="d", label="Model", options=options, default="opt0", height=10),
            CheckboxField(key="c", label="Cache"),
        ]
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(settings_form(items, placement="box")))

        with piped_session(rows=14) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN * 2 + ENTER)
                await wait_until(lambda: on_screen(session, "│opt0"))
                frame = "\n".join(screen_lines(session))
                assert "Window too small" not in frame
                inp.send_text(DOWN * 6)
                await wait_until(lambda: on_screen(session, "│opt6"))
                frame = "\n".join(screen_lines(session))
                assert "Window too small" not in frame
                assert "│opt0" not in frame  # scrolled: the menu's first option is out of view
                inp.send_text(ENTER)
                await wait_until(lambda: not on_screen(session, "│opt"))  # the menu closed
                inp.send_text(TAB * 2 + ENTER)
                await wait_until(lambda: results == [{"a": False, "b": False, "d": "opt6", "c": False}])

            await run_with(session, handler, script)


class TestBoxMenuFloatsOnClose:
    async def test_closing_a_dialog_with_its_menu_open_leaves_no_stale_float(self):
        items = [DropdownField(key="d", label="Model", options=["alpha", "beta"], default="beta")]
        closed: list[bool] = []

        async def handler(text: str) -> None:
            await session.show_dialog(settings_form(items, placement="box"))
            closed.append(True)

        with piped_session(rows=30) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(ENTER)
                await wait_until(lambda: on_screen(session, "alpha"))
                assert len(session.app.layout.container.floats) > 1
                # Escape would only shut the menu: close the form under it.
                session._dialogs._current_dialog.cancel()
                await wait_until(lambda: closed == [True])
                assert len(session.app.layout.container.floats) == 1
                await wait_until(lambda: not on_screen(session, "alpha"))

            await run_with(session, handler, script)


class TestSessionRepaintsAfterShrinking:
    """The session repaints (clears the screen and scrollback and prints
    the transcript again) once the terminal stops shrinking."""

    DELAY = 0.02

    @classmethod
    async def _resize(cls, **size: int) -> int:
        """Resize a running session's terminal (24x80) to ``size``; the
        repaints that follow."""

        async def handler(text: str) -> None:
            pass

        with piped_session(rows=24, columns=80) as (session, inp):
            session._shrinks._delay = cls.DELAY
            with patch.object(session, "_repaint_console") as repaint:

                async def script(run: asyncio.Task[None]) -> None:
                    renders = session.app.render_counter
                    session.app.output.resize(**size)
                    session.app.invalidate()
                    await wait_until(lambda: session.app.render_counter > renders)
                    # The repaint, if one was due, has happened.
                    await wait_until(lambda: session._shrinks._handle is None)

                await run_with(session, handler, script)
            return repaint.call_count

    async def test_a_narrower_terminal_repaints(self):
        assert await self._resize(columns=60) == 1

    async def test_a_shorter_terminal_repaints(self):
        assert await self._resize(rows=12) == 1

    async def test_a_wider_terminal_does_not_repaint(self):
        assert await self._resize(columns=100) == 0


class TestRepaintWhileRunning:
    """A repaint (set_theme(repaint=True), a shrink) of a running session is
    one run_in_terminal job: the screen and scrollback cleared and the
    transcript printed in one go."""

    async def test_two_repaints_in_a_row_print_the_transcript_once(self):
        output = _RecordingOutput(24)

        async def handler(text: str) -> None:
            pass

        with create_pipe_input() as inp, create_app_session(input=inp, output=output):
            session = ThinkingPromptSession()

            async def script(run: asyncio.Task[None]) -> None:
                for i in range(30):
                    session.add_response(f"entry {i}")
                await wait_until(lambda: "entry 29\n" in output.text())
                renders = session.app.render_counter
                session._repaint_console()
                session._repaint_console()
                session.add_response("after")  # printed behind both repaints
                await wait_until(lambda: "after\n" in output.text())

                text = output.text()
                assert text.count("\x1b[3J") == 2
                repainted = text[text.rindex("\x1b[3J"):]
                assert [repainted.count(f"entry {i}\n") for i in range(30)] == [1] * 30
                assert repainted.index("entry 29\n") < repainted.index("after\n")
                # The UI is redrawn once a job, not once an entry.
                assert session.app.render_counter - renders < 10

            await run_with(session, handler, script)


class TestDialogFields:
    """Fields on any Dialog, driven through a running session."""

    async def test_a_dialog_shown_twice_keeps_its_values_and_one_menu_float(self):
        dialog = Dialog(
            "T",
            fields=[DropdownField("d", "Model", options=["alpha", "beta"], default="alpha")],
            width=40,
            placement="box",
        )
        dialog.buttons = [ButtonConfig("OK", handler=lambda: dialog.set_result(dialog.values))]
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session(rows=30) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(ENTER)                 # open the menu
                await wait_until(lambda: on_screen(session, "│beta"))
                inp.send_text(DOWN + ENTER)          # beta
                await wait_until(lambda: not on_screen(session, "│beta"))
                inp.send_text(TAB + ENTER)           # OK
                await wait_until(lambda: results == [{"d": "beta"}])
                assert len(session.app.layout.container.floats) == 1
                inp.send_text("again" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                assert on_screen(session, "beta")    # still beta
                inp.send_text(TAB + ENTER)
                await wait_until(lambda: results == [{"d": "beta"}, {"d": "beta"}])
                assert len(session.app.layout.container.floats) == 1

            await run_with(session, handler, script)

    async def test_tab_during_a_text_edit_keeps_the_edit(self):
        dialog = Dialog(
            "T",
            fields=[TextField("user", "Username"), TextField("pw", "Password")],
            placement="box",
        )
        dialog.buttons = [ButtonConfig("OK", handler=lambda: dialog.set_result(dialog.values))]
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(ENTER + "bob")         # edit the first field
                await wait_until(lambda: on_screen(session, "bob"))
                inp.send_text(TAB)                   # ignored while editing
                inp.send_text(ENTER)                 # keep
                await wait_until(lambda: not dialog._is_editing())
                inp.send_text(TAB + TAB + ENTER)     # Password, then OK
                await wait_until(lambda: results == [{"user": "bob", "pw": ""}])

            await run_with(session, handler, script)

    async def test_tab_with_a_menu_open_keeps_it_open(self):
        dialog = Dialog(
            "T",
            fields=[
                DropdownField("d", "Model", options=["alpha", "beta"], default="alpha"),
                CheckboxField("c", "Cache"),
            ],
            width=40,
            placement="box",
        )
        dialog.buttons = [ButtonConfig("OK", handler=lambda: dialog.set_result(dialog.values))]
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session(rows=30) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(ENTER)                 # open the menu
                await wait_until(lambda: on_screen(session, "│beta"))
                # Spent in the open menu: a Tab or Shift+Tab that got out
                # would move the cursor, and ↓ or Enter would act elsewhere.
                inp.send_text(TAB + DOWN)            # beta
                inp.send_text(SHIFT_TAB + ENTER)     # kept; the menu closes
                inp.send_text(TAB + TAB + ENTER)     # Cache, then OK
                await wait_until(lambda: results == [{"d": "beta", "c": False}])

            await run_with(session, handler, script)

    async def test_a_text_area_above_the_fields_keeps_its_keys(self):
        area = TextArea(multiline=False)
        dialog = Dialog("T", area, fields=[CheckboxField("on", "On")], placement="box")
        dialog.buttons = [
            ButtonConfig("OK", handler=lambda: dialog.set_result((area.text, dialog.values))),
        ]
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text("hi")                  # into the text area, where the cursor starts
                inp.send_text(TAB + " ")             # into the field: check it
                inp.send_text(TAB + ENTER)           # past the last field: OK
                await wait_until(lambda: results == [("hi", {"on": True})])

            await run_with(session, handler, script)

    @pytest.mark.parametrize("key", [DOWN, TAB], ids=["down", "tab"])
    async def test_a_list_with_no_options_is_skipped(self, key):
        dialog = Dialog(
            "T",
            fields=[
                SelectField("s", "Size", options=["a", "b"]),
                RadioField("r", "Mode", options=[]),
                CheckboxField("c", "Cache"),
            ],
            placement="box",
        )
        dialog.buttons = [ButtonConfig("OK", handler=lambda: dialog.set_result(dialog.values))]
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(key + " ")             # past the empty list: check Cache
                inp.send_text(TAB + ENTER)           # OK
                await wait_until(lambda: results == [{"s": None, "r": None, "c": True}])

            await run_with(session, handler, script)

    async def test_fields_without_buttons_escape_with_none_keeping_the_edits(self):
        dialog = Dialog("T", fields=[CheckboxField("on", "On")], placement="inline")
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                assert on_screen(session, "❯ On")
                inp.send_text(" " + ESCAPE)
                await wait_until(lambda: results == [None])
                assert dialog.values == {"on": True}

            await run_with(session, handler, script)

    async def test_tab_enters_a_radio_list_at_its_pick_and_shift_tab_goes_back(self):
        area = TextArea(multiline=False)
        dialog = Dialog(
            "T",
            area,
            fields=[RadioField("m", "Mode", options=["x", "y", "z"], default="z")],
            placement="box",
        )
        dialog.buttons = [
            ButtonConfig("OK", handler=lambda: dialog.set_result((area.text, dialog.values))),
        ]
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text("hi" + TAB)
                # The cursor (❯) is on the picked option, not the first.
                await wait_until(
                    lambda: any("❯" in ln and "(•) z" in ln for ln in screen_lines(session))
                )
                inp.send_text(SHIFT_TAB + "!")
                inp.send_text(TAB + TAB + ENTER)
                await wait_until(lambda: results == [("hi!", {"m": "z"})])

            await run_with(session, handler, script)

    async def test_an_auto_width_box_shows_a_long_label_whole(self):
        label = "Stream responses from the model"
        dialog = Dialog("T", fields=[CheckboxField("a", label)], placement="box")
        dialog.buttons = [ButtonConfig("OK")]
        closed: list[bool] = []

        async def handler(text: str) -> None:
            await session.show_dialog(dialog)
            closed.append(True)

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                line = next(line for line in screen_lines(session) if label in line)
                assert "false" in line
                inp.send_text(ESCAPE)
                await wait_until(lambda: closed == [True])

            await run_with(session, handler, script)

    @staticmethod
    def _radio_and_checkbox(radio_first: bool) -> Dialog:
        """A radio list (picked "b" of a-d) and a checkbox, with OK and Cancel."""
        radio = RadioField("m", "Mode", options=["a", "b", "c", "d"], default="b")
        check = CheckboxField("c", "Cache")
        dialog = Dialog(
            "T", fields=[radio, check] if radio_first else [check, radio], width=40, placement="box",
        )
        dialog.buttons = [
            ButtonConfig("OK", handler=lambda: dialog.set_result(dialog.values)),
            ButtonConfig("Cancel"),
        ]
        return dialog

    async def test_shift_tab_from_the_first_button_enters_the_last_field_at_its_pick(self):
        dialog = self._radio_and_checkbox(radio_first=False)
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(TAB + TAB)               # Mode, then OK
                inp.send_text(SHIFT_TAB)               # back to Mode, at b
                inp.send_text(UP + " ")                # a, picked
                inp.send_text(TAB + ENTER)             # OK
                await wait_until(lambda: results == [{"c": False, "m": "a"}])

            await run_with(session, handler, script)

    async def test_tab_from_the_last_button_wraps_to_the_first_field_at_its_pick(self):
        dialog = self._radio_and_checkbox(radio_first=True)
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(TAB + TAB + TAB)         # Cache, OK, Cancel
                inp.send_text(TAB)                     # round to Mode, at b
                inp.send_text(DOWN + " ")              # c, picked
                inp.send_text(TAB + TAB + ENTER)       # Cache, then OK
                await wait_until(lambda: results == [{"m": "c", "c": False}])

            await run_with(session, handler, script)

    async def test_without_buttons_tab_from_the_last_field_wraps_to_the_first_at_its_pick(self):
        dialog = self._radio_and_checkbox(radio_first=True)
        dialog.buttons = []
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(TAB + TAB)               # Cache, then round to Mode, at b
                inp.send_text(DOWN + " " + ESCAPE)     # c, picked
                await wait_until(lambda: results == [None])
                assert dialog.values == {"m": "c", "c": False}

            await run_with(session, handler, script)


def _choice_form(placement: str) -> Dialog:
    """A checkbox, a ChoiceField (picked "y") and a checkbox; OK returns the values."""
    dialog = Dialog(
        "T",
        fields=[
            CheckboxField("a", "A"),
            ChoiceField("c", "Answers", options=["x", "y", "z"], default="y"),
            CheckboxField("b", "B"),
        ],
        width=40,
        placement=placement,
    )
    dialog.buttons = [ButtonConfig("OK", handler=lambda: dialog.set_result(dialog.values))]
    return dialog


# From the last field to OK: Tab in a box, ↓ inline (the next stop is the action).
TO_OK = {"box": TAB, "inline": DOWN}


class TestChoiceFieldInAForm:
    """A ChoiceField among other fields works like a radio list: ↑↓ walk its
    options, Space or Enter picks one, and walking past changes nothing."""

    @pytest.mark.parametrize("placement", ["box", "inline"])
    async def test_walking_past_keeps_the_pick(self, placement):
        dialog = _choice_form(placement)
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN * 4 + TO_OK[placement] + ENTER)   # x, y, z, B, then OK
                await wait_until(lambda: results == [{"a": False, "c": "y", "b": False}])

            await run_with(session, handler, script)

    @pytest.mark.parametrize("placement", ["box", "inline"])
    async def test_enter_picks_and_the_cursor_stays(self, placement):
        dialog = _choice_form(placement)
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN * 3)                # z
                await wait_until(lambda: on_screen(session, "❯   z"))
                inp.send_text(ENTER)                   # picks z
                await wait_until(lambda: dialog.values["c"] == "z")
                inp.send_text(UP + ENTER)              # still on z: up to y, picks y
                await wait_until(lambda: dialog.values["c"] == "y")
                assert dialog_open(session)
                inp.send_text(DOWN * 2 + TO_OK[placement] + ENTER)   # z, B, then OK
                await wait_until(lambda: results == [{"a": False, "c": "y", "b": False}])

            await run_with(session, handler, script)

    async def test_space_picks_too(self):
        dialog = _choice_form("box")
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN + " ")              # x
                await wait_until(lambda: dialog.values["c"] == "x")
                inp.send_text(DOWN * 3 + TAB + ENTER)  # y, z, B, then OK
                await wait_until(lambda: results == [{"a": False, "c": "x", "b": False}])

            await run_with(session, handler, script)


def _choice_alone(
    placement: str, options: list[str] | None = None, text: str = "Pick:", default: str | None = None,
) -> Dialog:
    """A ChoiceField alone under a text body; OK returns its pick."""
    dialog = Dialog(
        "Theme",
        text,
        fields=[ChoiceField("c", "", options=options or ["x", "y", "z"], default=default)],
        placement=placement,
    )
    dialog.buttons = [
        ButtonConfig("OK", handler=lambda: dialog.set_result(dialog.values["c"])),
        ButtonConfig("Cancel"),
    ]
    return dialog


class TestChoiceFieldAlone:
    """A ChoiceField alone in its dialog: ↑↓ walk the options, and Enter
    picks the one under the cursor and presses the first button."""

    @pytest.mark.parametrize("placement", ["box", "inline"])
    async def test_enter_picks_the_option_under_the_cursor_and_presses_ok(self, placement):
        dialog = _choice_alone(placement)
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                assert on_screen(session, "❯ x"), screen_lines(session)
                inp.send_text(DOWN)
                await wait_until(lambda: on_screen(session, "❯ y"))
                inp.send_text(ENTER)
                await wait_until(lambda: results == ["y"])

            await run_with(session, handler, script)

    async def test_walking_doesnt_change_the_pick(self):
        dialog = _choice_alone("box")
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN + DOWN)             # z, not picked
                await wait_until(lambda: on_screen(session, "❯ z"))
                inp.send_text(TAB + ENTER)             # OK
                await wait_until(lambda: results == ["x"])

            await run_with(session, handler, script)

    async def test_tab_tab_enter_presses_cancel(self):
        dialog = _choice_alone("box")
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(TAB + TAB + ENTER)       # OK, Cancel, then press it
                await wait_until(lambda: results == [None])

            await run_with(session, handler, script)

    async def test_shift_tab_from_ok_comes_back_to_the_pick(self):
        dialog = _choice_alone("box", default="y")
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(TAB)                     # OK
                await wait_until(lambda: not on_screen(session, "❯ y"))
                inp.send_text(SHIFT_TAB)               # the pick
                await wait_until(lambda: on_screen(session, "❯ y"))
                inp.send_text(UP + ENTER)              # x, picked; then OK
                await wait_until(lambda: results == ["x"])

            await run_with(session, handler, script)

    async def test_inline_down_past_the_last_option_reaches_the_actions(self):
        dialog = _choice_alone("inline")
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN * 3)                # y, z, then on to 1. OK
                await wait_until(lambda: cursor_row(session) == "❯ 1. OK")
                inp.send_text(ENTER)
                await wait_until(lambda: results == ["x"])   # walked past: still x

            await run_with(session, handler, script)

    @pytest.mark.parametrize("placement", ["box", "inline"])
    async def test_with_no_buttons_enter_closes_with_the_pick(self, placement):
        dialog = Dialog(
            "Theme", "Pick:", fields=[ChoiceField("c", "", options=["x", "y", "z"])], placement=placement
        )
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(dialog))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN)
                await wait_until(lambda: on_screen(session, "❯ y"))
                inp.send_text(ENTER)
                await wait_until(lambda: results == ["y"])

            await run_with(session, handler, script)
