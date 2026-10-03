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
from prompt_toolkit.output import DummyOutput

from thinking_prompt import ButtonConfig, Dialog, TextItem, ThinkingPromptSession

CTRL_A = "\x01"
CTRL_C = "\x03"
CTRL_D = "\x04"
CTRL_S = "\x13"
ENTER = "\r"
ESCAPE = "\x1b"
TAB = "\t"
SHIFT_TAB = "\x1b[Z"
DOWN = "\x1b[B"


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
                await wait_until(lambda: session._dialog_manager is not None
                                 and session._dialog_manager._visible)
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


def dialog_open(session: ThinkingPromptSession) -> bool:
    dm = session._dialog_manager
    return dm is not None and dm._visible


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
                await wait_until(lambda: dialog_open(session))
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
                await wait_until(lambda: dialog_open(session))
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
                await wait_until(lambda: dialog_open(session))
                inp.send_text(DOWN + ENTER + TAB + ENTER)  # select "Dark", then OK
                await wait_until(lambda: results == ["Dark"])

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
