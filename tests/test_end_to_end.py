"""End-to-end tests: drive a running session with piped keystrokes.

Unit tests poke the key-binding handlers directly, which misses bugs that
only appear when the real key processor, input loop and Application run
together (e.g. several keys arriving in one read). These tests run
``session.run_async()`` against a pipe input and ``DummyOutput``.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Iterator
from contextlib import contextmanager
from typing import Any, Callable

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import PipeInput, create_pipe_input
from prompt_toolkit.layout import BufferControl
from prompt_toolkit.output import DummyOutput

from thinking_prompt import (
    ButtonConfig,
    CheckboxItem,
    ChecklistItem,
    Dialog,
    InlineSelectItem,
    RadioItem,
    TextItem,
    ThinkingPromptSession,
)

CTRL_A = "\x01"
CTRL_C = "\x03"
CTRL_D = "\x04"
CTRL_S = "\x13"
ENTER = "\r"
ESCAPE = "\x1b"
TAB = "\t"
SHIFT_TAB = "\x1b[Z"
DOWN = "\x1b[B"
UP = "\x1b[A"
RIGHT = "\x1b[C"


@contextmanager
def piped_session(**kwargs: Any) -> Iterator[tuple[ThinkingPromptSession, PipeInput]]:
    """A session whose Application reads from a pipe and renders nowhere."""
    with create_pipe_input() as inp, create_app_session(input=inp, output=DummyOutput()):
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
                await session.show_settings_dialog(
                    "Settings", [TextItem(key="name", label="Name", default="abc")]
                )
            )

        with piped_session() as (session, inp):

            def editing() -> bool:
                dm = session._dialog_manager
                dialog = dm._current_dialog if dm else None
                return dialog is not None and dialog._controls[0].is_editing

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
                inp.send_text(CTRL_S)
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
                inp.send_text(DOWN + ENTER + TAB + ENTER)  # select "Dark", then OK
                await wait_until(lambda: results == ["Dark"])

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
                inp.send_text(DOWN + ENTER)  # before the dialog's first render
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
        MAX_ROWS instead of sizing to its actual content (fullscreen mode,
        or any render with rows to spare)."""
        from prompt_toolkit.layout import Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.layout.layout import walk

        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_dialog(self._dialog()))

        with piped_session() as (session, inp):
            # Fullscreen mode gives the layout spare height (history fills
            # whatever the dialog doesn't use) on a 40-row DummyOutput.
            session._is_fullscreen = True
            session._invalidate()

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


class TestInlineSettings:
    """The settings dialog inline: settings rows, then Save / Cancel, one cursor."""

    @staticmethod
    def _items() -> list[Any]:
        return [
            InlineSelectItem(key="model", label="Model", options=["a", "b", "c"], default="a"),
            CheckboxItem(key="stream", label="Stream", default=False),
            TextItem(key="name", label="Name", default=""),
        ]

    @staticmethod
    def _editing(session: ThinkingPromptSession) -> bool:
        dm = session._dialog_manager
        dialog = dm._current_dialog if dm else None
        return dialog is not None and dialog._is_editing()

    async def test_one_cursor_walks_the_settings_then_the_actions(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_settings_dialog("Settings", self._items(), placement="inline"))

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

    async def test_ctrl_s_saves(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_settings_dialog("Settings", self._items(), placement="inline"))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(DOWN + " " + CTRL_S)
                await wait_until(lambda: results == [{"stream": True}])

            await run_with(session, handler, script)

    async def test_escape_while_editing_text_only_ends_the_edit(self):
        results: list[Any] = []

        async def handler(text: str) -> None:
            results.append(await session.show_settings_dialog("Settings", self._items(), placement="inline"))

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
            results.append(await session.show_settings_dialog("Settings", [], placement="inline"))

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
            results.append(await session.show_settings_dialog("Settings", self._items()))

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(RIGHT + DOWN + " ")  # Model: b; Stream: on
                inp.send_text(TAB + TAB + ENTER)   # Name, then the Save button
                await wait_until(lambda: results == [{"model": "b", "stream": True}])

            await run_with(session, handler, script)

    async def test_check_and_radio_lists_one_option_per_line(self):
        results: list[Any] = []
        items = [
            ChecklistItem(key="tools", label="Tools", options=["search", "code"], default=("search",)),
            RadioItem(key="mode", label="Mode", options=["fast", "careful"], default="fast"),
        ]

        async def handler(text: str) -> None:
            results.append(await session.show_settings_dialog("Settings", items, placement="inline"))

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
                inp.send_text(TAB + TAB + ENTER)  # files, then the OK button
                await wait_until(lambda: results == [["code"]])

            await run_with(session, handler, script)
