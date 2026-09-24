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

from thinking_prompt import TextItem, ThinkingPromptSession

CTRL_A = "\x01"
CTRL_C = "\x03"
CTRL_D = "\x04"
CTRL_S = "\x13"
ENTER = "\r"


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
