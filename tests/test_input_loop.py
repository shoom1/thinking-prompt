"""The pull loop: ``async with session:`` runs the app, ``prompt_async()``
reads an input, ``query()`` runs one input's work as the query Ctrl+C
cancels."""
from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from collections.abc import Awaitable
from contextlib import suppress
from typing import Callable

import pytest

from tests.helpers import transcript_texts
from tests.test_end_to_end import (
    CTRL_C,
    CTRL_D,
    ENTER,
    UP,
    dialog_rendered,
    done_frame,
    echoed_inputs,
    piped_session,
    screen_lines,
    wait_until,
    waiting_for_input,
)
from thinking_prompt import ThinkingPromptSession


async def run_loop(
    session: ThinkingPromptSession,
    body: Callable[[], Awaitable[None]],
    script: Callable[[asyncio.Task[None]], Awaitable[None]],
) -> None:
    """Run ``body`` inside ``async with session:`` while ``script`` drives
    the keys; tear down however it ends."""

    async def client() -> None:
        async with session:
            await body()

    run = asyncio.create_task(client())
    try:
        await wait_until(lambda: waiting_for_input(session) or run.done())
        await script(run)
    finally:
        if not run.done():
            session.exit()
        await asyncio.wait_for(run, timeout=2)


async def finished(run: asyncio.Task[None]) -> None:
    await asyncio.wait_for(asyncio.shield(run), timeout=2)


class TestLifetime:
    async def test_the_app_runs_inside_the_block_only(self):
        with piped_session() as (session, inp):
            assert not session.app.is_running
            async with session:
                assert session.app.is_running
            assert not session.app.is_running

    async def test_the_welcome_prints_on_entering(self):
        with piped_session() as (session, inp):
            welcomed: list[bool] = []
            session._print_welcome = lambda: welcomed.append(True)  # type: ignore[method-assign]
            async with session:
                assert welcomed == [True]

    async def test_a_dialog_the_loop_awaits_when_the_app_stops_raises_eof_error(self):
        """As prompt_async() in the same spot: nothing cancelled the loop's
        task, so it isn't left cancelling (3.11+: cancelling() is 0)."""
        from thinking_prompt import ButtonConfig, Dialog

        seen: list[object] = []
        with piped_session() as (session, inp):

            async def stop_soon() -> None:
                await wait_until(lambda: dialog_rendered(session))
                session.exit()  # a shutdown timer, a server push, ...

            stopper = asyncio.create_task(stop_soon())
            with pytest.raises(EOFError):
                async with session:
                    try:
                        await session.show_dialog(Dialog("Save?", "Save first?", [ButtonConfig("OK")]))
                    finally:
                        task = asyncio.current_task()
                        if hasattr(task, "cancelling"):
                            seen.append(task.cancelling())  # type: ignore[union-attr]
            await stopper
        assert seen in ([], [0])

    async def test_a_query_whose_sub_task_awaits_a_dialog_is_cancelled_when_the_app_stops(self):
        """The query awaits a task that awaits the dialog: the cancel reaches
        the dialog through it, and query() returns None, as for a dialog the
        query awaits itself."""
        from thinking_prompt import ButtonConfig, Dialog

        results: list[object] = []
        with piped_session() as (session, inp):

            async def respond() -> object:
                return await asyncio.ensure_future(
                    session.show_dialog(Dialog("Approve", "Run search?", [ButtonConfig("OK")]))
                )

            async def body() -> None:
                await session.prompt_async()
                results.append(await session.query(respond()))
                with suppress(EOFError):
                    await session.prompt_async()

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: dialog_rendered(session))
                session.exit()
                await finished(run)

            await run_loop(session, body, script)
        assert results == [None]

    async def test_an_error_in_the_block_stops_the_app_and_propagates(self):
        with piped_session() as (session, inp):
            with pytest.raises(ValueError, match="boom"):
                async with session:
                    raise ValueError("boom")
            assert not session.app.is_running
            async with session:  # and it can run again
                assert session.app.is_running

    async def test_a_box_the_loop_opens_ends_at_an_idle_ctrl_c(self):
        """The task in the block is the app's own: Ctrl+C ends its boxes,
        as it ends a startup box under run_async(), and doesn't exit."""
        with piped_session() as (session, inp):

            async def body() -> None:
                session.start_thinking(title="status").append("starting\n")
                with suppress(EOFError):
                    await session.prompt_async()

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text(CTRL_C)
                await wait_until(lambda: not session._manager.has_active_boxes)
                assert session.app.is_running
                assert "starting\n" in transcript_texts(session._display)
                session.exit()
                await finished(run)

            await run_loop(session, body, script)

    async def test_entering_twice_is_refused(self):
        with piped_session() as (session, inp):
            async with session:
                with pytest.raises(RuntimeError, match="already running"):
                    async with session:
                        pass
                with pytest.raises(RuntimeError, match="already running"):
                    await session.run_async(lambda text: None)


class TestPromptAsync:
    async def test_returns_each_line_and_echoes_it(self):
        lines: list[str] = []
        with piped_session() as (session, inp):

            async def body() -> None:
                while len(lines) < 2:
                    lines.append(await session.prompt_async())

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("one" + ENTER)
                await wait_until(lambda: lines == ["one"] and waiting_for_input(session))
                inp.send_text("two" + ENTER)
                await finished(run)

            await run_loop(session, body, script)
            assert lines == ["one", "two"]
            assert echoed_inputs(session) == ["one", "two"]

    async def test_outside_the_block_it_says_where_it_belongs(self):
        with piped_session() as (session, inp), pytest.raises(
            RuntimeError, match="async with session"
        ):
            # Bounded: it used to wait forever here.
            await asyncio.wait_for(session.prompt_async(), timeout=1)

    async def test_after_ctrl_d_it_raises_eof_error_every_time(self):
        raised: list[str] = []
        with piped_session() as (session, inp):

            async def body() -> None:
                for _ in range(2):
                    with suppress(EOFError):
                        await session.prompt_async()
                        continue
                    raised.append("eof")

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text(CTRL_D)
                await finished(run)

            await run_loop(session, body, script)
        assert raised == ["eof", "eof"]

    async def test_exit_wakes_a_waiting_prompt_with_eof_error(self):
        raised: list[str] = []
        with piped_session() as (session, inp):

            async def body() -> None:
                try:
                    await session.prompt_async()
                except EOFError:
                    raised.append("eof")

            async def script(run: asyncio.Task[None]) -> None:
                session.exit()
                await finished(run)

            await run_loop(session, body, script)
        assert raised == ["eof"]

    async def test_ctrl_c_at_an_idle_prompt_says_how_to_exit(self):
        lines: list[str] = []
        with piped_session() as (session, inp):

            async def body() -> None:
                lines.append(await session.prompt_async())

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text(CTRL_C)
                await wait_until(lambda: session.status_text == session._IDLE_STATUS)
                assert session.app.is_running and waiting_for_input(session)
                inp.send_text("hello" + ENTER)
                await finished(run)

            await run_loop(session, body, script)
        assert lines == ["hello"]

    async def test_ctrl_c_clears_a_typed_line(self):
        lines: list[str] = []
        with piped_session(status_text="READY") as (session, inp):

            async def body() -> None:
                lines.append(await session.prompt_async())

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("draft")
                await wait_until(lambda: session._default_buffer.text == "draft")
                inp.send_text(CTRL_C + "x")  # "x" lands once the Ctrl+C is handled
                await wait_until(lambda: session._default_buffer.text == "x")
                assert session.status_text == "READY"
                inp.send_text(ENTER)
                await finished(run)

            await run_loop(session, body, script)
        assert lines == ["x"]

    async def test_ctrl_c_under_a_background_dialog_keeps_the_draft_quietly(self):
        """The dialog has the focus: Ctrl+C neither clears the prompt under
        it nor says Ctrl+D exits (in the dialog, it doesn't)."""
        with piped_session(status_text="READY") as (session, inp):

            async def body() -> None:
                with suppress(EOFError):
                    await session.prompt_async()

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("draft")
                await wait_until(lambda: session._default_buffer.text == "draft")
                shown = asyncio.ensure_future(session.message_dialog("Note", "hello"))
                await wait_until(lambda: dialog_rendered(session))
                inp.send_text(CTRL_C + ENTER)  # Enter presses OK once the Ctrl+C is handled
                await asyncio.wait_for(shown, 2)
                assert session._default_buffer.text == "draft"
                assert session.status_text == "READY"

            await run_loop(session, body, script)

    async def test_a_second_waiter_is_refused_and_pointed_to_a_dialog(self):
        """The prompt's next line is one task's: a task beside the input
        loop asks with a dialog."""
        with piped_session() as (session, inp):

            async def body() -> None:
                first = asyncio.ensure_future(session.prompt_async())
                await wait_until(lambda: waiting_for_input(session))
                with pytest.raises(RuntimeError, match="already waiting.*dialog"):
                    await session.prompt_async()
                first.cancel()
                with suppress(asyncio.CancelledError):
                    await first

            async def script(run: asyncio.Task[None]) -> None:
                await finished(run)

            await run_loop(session, body, script)

    async def test_cancelling_the_waiting_task_cancels_it(self):
        """Not a Ctrl+C: the caller's own cancellation stays a cancellation."""
        with piped_session() as (session, inp):

            async def body() -> None:
                waiter = asyncio.ensure_future(session.prompt_async())
                await wait_until(lambda: waiting_for_input(session))
                waiter.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiter
                assert not waiting_for_input(session)

            async def script(run: asyncio.Task[None]) -> None:
                await finished(run)

            await run_loop(session, body, script)


async def forever(session: ThinkingPromptSession, text: str, started: list[str]) -> str:
    """A query that opens a box, writes to it, and waits until cancelled."""
    box = session.start_thinking(title=text)
    box.append(f"{text} working\n")
    started.append(text)
    await asyncio.Event().wait()
    return text


class TestQuery:
    async def test_returns_the_coroutines_result(self):
        results: list[object] = []
        with piped_session() as (session, inp):

            async def respond(text: str) -> str:
                return text.upper()

            async def body() -> None:
                results.append(await session.query(respond(await session.prompt_async())))

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("hi" + ENTER)
                await finished(run)

            await run_loop(session, body, script)
        assert results == ["HI"]

    async def test_boxes_it_leaves_open_end_with_it(self):
        with piped_session() as (session, inp):

            async def respond() -> None:
                session.start_thinking(title="T").append("working\n")

            async def body() -> None:
                await session.query(respond())
                assert not session._manager.has_active_boxes

            async def script(run: asyncio.Task[None]) -> None:
                await finished(run)

            await run_loop(session, body, script)
            assert "working\n" in transcript_texts(session._display)

    async def test_ctrl_c_cancels_the_query_and_the_loop_goes_on(self):
        results: list[object] = []
        started: list[str] = []
        with piped_session() as (session, inp):

            async def body() -> None:
                while True:
                    try:
                        text = await session.prompt_async()
                    except (EOFError, KeyboardInterrupt):
                        return
                    results.append(await session.query(forever(session, text, started)))

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("first" + ENTER)
                await wait_until(lambda: started == ["first"])
                inp.send_text(CTRL_C)
                await wait_until(lambda: results == [None] and waiting_for_input(session))
                texts = transcript_texts(session._display)
                assert texts[-2:] == ["first working\n", "Operation cancelled...\n"]

            await run_loop(session, body, script)

    async def test_an_error_propagates_after_its_boxes_are_echoed(self):
        with piped_session() as (session, inp):

            async def respond() -> None:
                session.start_thinking(title="T").append("partial\n")
                raise KeyError("x")

            async def body() -> None:
                with pytest.raises(KeyError):
                    await session.query(respond())
                assert "partial\n" in transcript_texts(session._display)

            async def script(run: asyncio.Task[None]) -> None:
                await finished(run)

            await run_loop(session, body, script)

    async def test_one_query_at_a_time(self):
        with piped_session() as (session, inp):

            async def inner() -> None:
                return None

            async def outer() -> None:
                coro = inner()
                with pytest.raises(RuntimeError, match="already running"):
                    await session.query(coro)

            async def body() -> None:
                await session.query(outer())

            async def script(run: asyncio.Task[None]) -> None:
                await finished(run)

            await run_loop(session, body, script)

    async def test_a_query_started_while_the_last_one_cleans_up_is_refused(self):
        # The first query's work is done, but query() returns a loop turn
        # later, after its cleanup. A second query accepted in that gap was
        # unregistered by that cleanup: Ctrl+C then stopped the app and left
        # the second query running.
        outcome: list[str] = []
        with piped_session() as (session, inp):

            async def second() -> None:
                return None

            async def try_second() -> None:
                try:
                    await session.query(second())
                    outcome.append("ran")
                except RuntimeError as error:
                    outcome.append(str(error))

            async def first() -> None:
                # Runs after this task is done, before query() resumes.
                asyncio.get_running_loop().call_soon(lambda: asyncio.ensure_future(try_second()))

            async def body() -> None:
                await session.query(first())
                await wait_until(lambda: bool(outcome))

            async def script(run: asyncio.Task[None]) -> None:
                await finished(run)

            await run_loop(session, body, script)
        assert len(outcome) == 1 and "already running" in outcome[0], outcome

    async def test_it_takes_a_coroutine_not_a_function(self):
        with piped_session() as (session, inp):

            async def respond() -> None:
                return None

            async with session:
                with pytest.raises(TypeError, match=r"query\(respond\(text\)\)"):
                    await session.query(respond)  # type: ignore[arg-type]

    async def test_outside_the_block_it_is_refused(self):
        with piped_session() as (session, inp):
            coro = asyncio.sleep(0)
            with pytest.raises(RuntimeError, match="async with session"):
                await session.query(coro)

    async def test_once_the_app_stops_it_runs_nothing_and_returns_none(self):
        ran: list[str] = []
        with piped_session() as (session, inp):

            async def work(when: str) -> str:
                ran.append(when)
                return when

            async with session:
                await wait_until(lambda: session.app.is_running)
                session.exit()  # told to stop: the app takes a few loop turns
                told = work("told to stop")
                assert await session.query(told) is None
                await wait_until(lambda: session._app_run is not None and session._app_run.done())
                stopped = work("stopped")
                assert await session.query(stopped) is None
        assert ran == []
        # Closed, not left for a "never awaited" warning.
        assert inspect.getcoroutinestate(told) == inspect.CORO_CLOSED
        assert inspect.getcoroutinestate(stopped) == inspect.CORO_CLOSED

    async def test_a_loop_of_queries_ignoring_none_lets_the_app_finish_stopping(self):
        # Refused at once, query() still gives the loop a turn: without it,
        # a loop of queries that ignores the None never let the app stop,
        # and Ctrl+C couldn't reach it.
        async def step() -> None:
            return None

        with piped_session() as (session, inp):
            async with session:
                await wait_until(lambda: session.app.is_running)
                run = session._app_run
                assert run is not None
                session.exit()
                for _ in range(1000):
                    await session.query(step())
                    if run.done():
                        break
                assert run.done()

    async def test_an_error_as_the_caller_cancels_it_is_logged(self, caplog):
        # The caller is cancelled, so the query's error has nowhere to go:
        # it was left for asyncio's "Task exception was never retrieved".
        with piped_session() as (session, inp):
            started = asyncio.Event()

            async def work() -> None:
                try:
                    started.set()
                    await asyncio.Event().wait()
                finally:
                    raise ValueError("cleanup broke")

            async with session:
                await wait_until(lambda: session.app.is_running)
                caller = asyncio.ensure_future(session.query(work()))
                await started.wait()
                child = session._foreground
                assert child is not None
                with caplog.at_level(logging.ERROR, logger="thinking_prompt"):
                    caller.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await caller
        errors = [r for r in caplog.records if r.exc_info and isinstance(r.exc_info[1], ValueError)]
        assert [str(r.exc_info[1]) for r in errors] == ["cleanup broke"]  # type: ignore[index]
        assert not child._log_traceback  # type: ignore[attr-defined]  # retrieved: asyncio won't report it

    async def test_ctrl_d_leaves_a_running_query_and_says_how_to_stop_it(self):
        results: list[object] = []
        started: list[str] = []
        with piped_session() as (session, inp):

            async def body() -> None:
                text = await session.prompt_async()
                results.append(await session.query(forever(session, text, started)))

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: started == ["go"])
                inp.send_text(CTRL_D)
                await wait_until(lambda: session.status_text == session._BUSY_STATUS)
                assert session.app.is_running and not run.done()
                inp.send_text(CTRL_C)
                await finished(run)

            await run_loop(session, body, script)
        assert results == [None]

    async def test_a_query_can_ask_a_follow_up(self):
        results: list[object] = []
        with piped_session() as (session, inp):

            async def respond() -> str:
                return await session.prompt_async()

            async def body() -> None:
                await session.prompt_async()
                results.append(await session.query(respond()))

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("question" + ENTER)
                await wait_until(lambda: session._foreground is not None and waiting_for_input(session))
                inp.send_text("answer" + ENTER)
                await finished(run)

            await run_loop(session, body, script)
        assert results == ["answer"]

    async def test_ctrl_c_during_a_follow_up_ends_the_whole_query(self):
        results: list[object] = []
        with piped_session() as (session, inp):

            async def respond() -> str:
                return await session.prompt_async()

            async def body() -> None:
                await session.prompt_async()
                results.append(await session.query(respond()))
                results.append(await session.prompt_async())

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("question" + ENTER)
                await wait_until(lambda: session._foreground is not None and waiting_for_input(session))
                inp.send_text(CTRL_C)
                await wait_until(lambda: results == [None] and waiting_for_input(session))
                inp.send_text("next" + ENTER)
                await finished(run)

            await run_loop(session, body, script)
        assert results == [None, "next"]


class TestCtrlDAtAFollowUp:
    """Ctrl+D while a query asks a follow-up does nothing: the query is
    running, and Ctrl+C is what stops it."""

    async def test_the_query_still_gets_its_answer(self):
        results: list[object] = []
        with piped_session() as (session, inp):

            async def respond() -> str:
                return await session.prompt_async()

            async def body() -> None:
                await session.prompt_async()
                results.append(await session.query(respond()))

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("question" + ENTER)
                await wait_until(lambda: session._foreground is not None and waiting_for_input(session))
                inp.send_text(CTRL_D + "answer" + ENTER)
                await finished(run)

            await run_loop(session, body, script)
        assert results == ["answer"]

    async def test_a_handler_asking_still_gets_its_answer(self):
        from tests.test_end_to_end import run_with

        answers: list[str] = []

        async def handler(text: str) -> None:
            answers.append(await session.prompt_async())

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("question" + ENTER)
                await wait_until(lambda: session._foreground is not None and waiting_for_input(session))
                inp.send_text(CTRL_D + "answer" + ENTER)
                await wait_until(lambda: answers == ["answer"])
                assert not run.done()

            await run_with(session, handler, script)


class TestCancelOnce:
    """The session cancels a query once: a query unwinding, its finally
    blocks awaiting their cleanup, isn't cancelled again by the app stopping
    or its caller being cancelled. Each Ctrl+C cancels again: the way out
    of a cleanup that hangs."""

    @staticmethod
    def _work(log: list[str], started: asyncio.Event, cleaning: asyncio.Event) -> Callable[[], Awaitable[None]]:
        async def work() -> None:
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                try:
                    await asyncio.sleep(0.2)
                    log.append("cleaned up")
                except asyncio.CancelledError:
                    log.append("cleanup cancelled")
                    raise

        return work

    async def test_exit_during_a_query_lets_its_cleanup_finish(self):
        log: list[str] = []
        started, cleaning = asyncio.Event(), asyncio.Event()
        work = self._work(log, started, cleaning)
        with piped_session() as (session, inp):

            async def body() -> None:
                await session.prompt_async()
                assert await session.query(work()) is None

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await started.wait()
                session.exit()
                await finished(run)

            await run_loop(session, body, script)
        assert log == ["cleaned up"]

    async def test_exit_during_a_handler_lets_its_cleanup_finish(self):
        from tests.test_end_to_end import run_with

        log: list[str] = []
        started, cleaning = asyncio.Event(), asyncio.Event()
        work = self._work(log, started, cleaning)

        async def handler(text: str) -> None:
            await work()

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await started.wait()
                session.exit()
                await finished(run)

            await run_with(session, handler, script)
        assert log == ["cleaned up"]

    async def test_exit_after_ctrl_c_lets_the_cleanup_finish(self):
        from tests.test_end_to_end import run_with

        log: list[str] = []
        started, cleaning = asyncio.Event(), asyncio.Event()
        work = self._work(log, started, cleaning)

        async def handler(text: str) -> None:
            await work()

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await started.wait()
                inp.send_text(CTRL_C)
                await cleaning.wait()
                session.exit()
                await finished(run)

            await run_with(session, handler, script)
        assert log == ["cleaned up"]

    async def test_cancelling_the_caller_after_ctrl_c_lets_the_cleanup_finish(self):
        log: list[str] = []
        started, cleaning = asyncio.Event(), asyncio.Event()
        work = self._work(log, started, cleaning)
        with piped_session() as (session, inp):

            async def body() -> None:
                caller = asyncio.ensure_future(session.query(work()))
                await started.wait()
                inp.send_text(CTRL_C)
                await cleaning.wait()
                caller.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await caller

            async def script(run: asyncio.Task[None]) -> None:
                await finished(run)

            await run_loop(session, body, script)
        assert log == ["cleaned up"]

    async def test_a_second_ctrl_c_stops_the_cleanup(self):
        log: list[str] = []
        started, cleaning = asyncio.Event(), asyncio.Event()
        work = self._work(log, started, cleaning)
        with piped_session() as (session, inp):

            async def body() -> None:
                await session.prompt_async()
                assert await session.query(work()) is None

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await started.wait()
                inp.send_text(CTRL_C)
                await cleaning.wait()
                inp.send_text(CTRL_C)
                await finished(run)

            await run_loop(session, body, script)
        assert log == ["cleanup cancelled"]


class TestExitFromTheQuery:
    """exit() called by the running query asks the session to stop once the
    query ends: the code after it runs, with the app up. Called from
    anywhere else, it stops the app at once (see TestCancelOnce)."""

    async def test_a_handler_runs_to_its_end_then_the_session_exits(self):
        from tests.test_end_to_end import run_with

        seen: list[bool] = []

        async def handler(text: str) -> None:
            session.exit()
            await asyncio.sleep(0.05)  # a real await: no cancel arrives
            seen.append(session.app.is_running and not session.app.is_done)
            session.add_response("goodbye")

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("/quit" + ENTER)
                await finished(run)

            await run_with(session, handler, script)
        assert seen == [True]
        assert "goodbye" in transcript_texts(session._display)[-1]

    async def test_a_query_runs_to_its_end_and_returns_its_result(self):
        results: list[object] = []
        with piped_session() as (session, inp):

            async def respond() -> str:
                session.exit()
                await asyncio.sleep(0.05)
                return "done"

            async def body() -> None:
                while True:
                    try:
                        await session.prompt_async()
                    except EOFError:
                        results.append("EOF")
                        return
                    results.append(await session.query(respond()))

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("/quit" + ENTER)
                await finished(run)

            await run_loop(session, body, script)
        assert results == ["done", "EOF"]

    async def test_after_exit_the_query_gets_no_more_input(self):
        """The session was told to stop: prompt_async() raises EOFError, as
        it does once the app has stopped."""
        results: list[str] = []
        with piped_session() as (session, inp):

            async def respond() -> None:
                session.exit()
                try:
                    await session.prompt_async()
                except EOFError:
                    results.append("EOF")

            async def body() -> None:
                await session.prompt_async()
                await session.query(respond())

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("/quit" + ENTER)
                await finished(run)

            await run_loop(session, body, script)
        assert results == ["EOF"]

    async def test_a_task_waiting_for_input_gets_eof_error_at_once(self):
        """Told to stop, the session reads no more input: a task already
        waiting in prompt_async() isn't left to take the next line."""
        from tests.test_end_to_end import run_with

        got: list[str] = []
        finishing = asyncio.Event()

        async def asker() -> None:
            try:
                got.append(await session.prompt_async())
            except EOFError:
                got.append("EOF")

        async def handler(text: str) -> None:
            asyncio.ensure_future(asker())
            await asyncio.sleep(0.05)  # the task waits for input
            session.exit()
            await finishing.wait()

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("/quit" + ENTER)
                await wait_until(lambda: got == ["EOF"])
                assert session.app.is_running  # the handler is finishing
                finishing.set()
                await finished(run)

            await run_with(session, handler, script)

    async def test_ctrl_c_after_exit_cancels_the_query_then_the_session_exits(self):
        from tests.test_end_to_end import run_with

        async def handler(text: str) -> None:
            session.exit()
            async with session.thinking() as box:
                box.append("closing\n")
                await asyncio.sleep(3600)

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("/quit" + ENTER)
                await wait_until(lambda: session.is_thinking)
                assert session.app.is_running
                inp.send_text(CTRL_C)
                await finished(run)
                assert transcript_texts(session._display)[-1] == "Operation cancelled...\n"

            await run_with(session, handler, script)

    async def test_exit_from_a_task_the_query_started_stops_at_once(self):
        """Only the query itself is let finish: exit() from its sub-task
        stops the app now, and the query is cancelled with it."""
        from tests.test_end_to_end import run_with

        log: list[str] = []

        async def stop() -> None:
            session.exit()

        async def handler(text: str) -> None:
            asyncio.ensure_future(stop())
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                log.append("cancelled")
                raise

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await finished(run)

            await run_with(session, handler, script)
        assert log == ["cancelled"]

    async def test_exit_again_does_nothing_more(self):
        from tests.test_end_to_end import run_with

        async def handler(text: str) -> None:
            session.exit()
            session.exit()

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("/quit" + ENTER)
                await finished(run)
                session.exit()  # stopped: nothing to do

            await run_with(session, handler, script)
        assert not any("[ERROR]" in text for text in transcript_texts(session._display))

    async def test_exit_twice_from_elsewhere_does_nothing_more(self):
        """The app takes a few loop turns to stop: a second exit() meanwhile
        is a no-op, not prompt_toolkit's "Return value already set"."""
        with piped_session() as (session, inp):

            async def body() -> None:
                with suppress(EOFError):
                    await session.prompt_async()

            async def script(run: asyncio.Task[None]) -> None:
                session.exit()
                session.exit()
                await finished(run)

            await run_loop(session, body, script)


class TestOtherEventLoops:
    """The calls that wait on the session (prompt_async(), query(), dialogs)
    run on its event loop. Awaited on another thread's loop, prompt_async()
    took the typed line and never woke: refused instead, naming the way to
    hand a call over."""

    @staticmethod
    async def _on_a_threads_own_loop(make: Callable[[], Awaitable[object]]) -> object:
        """Await ``make()`` on a thread's own event loop: its result, or
        what it raised. A daemon thread, so a call that hangs fails the
        test rather than the run."""
        result: dict[str, object] = {}

        def run() -> None:
            try:
                result["value"] = asyncio.run(make())  # type: ignore[arg-type]
            except BaseException as exc:
                result["error"] = exc

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        await asyncio.to_thread(thread.join, 3)
        assert not thread.is_alive(), "the call never returned on the thread's loop"
        if "error" in result:
            raise result["error"]  # type: ignore[misc]
        return result.get("value")

    async def test_prompt_async_on_another_loop_is_refused(self):
        with piped_session() as (session, inp):
            async with session:
                with pytest.raises(RuntimeError, match="run_coroutine_threadsafe"):
                    await self._on_a_threads_own_loop(session.prompt_async)
                assert not waiting_for_input(session)

    async def test_query_on_another_loop_is_refused_and_its_coroutine_closed(self):
        ran: list[bool] = []

        async def work() -> None:
            ran.append(True)

        with piped_session() as (session, inp):
            async with session:
                with pytest.raises(RuntimeError, match="run_coroutine_threadsafe"):
                    await self._on_a_threads_own_loop(lambda: session.query(work()))
                assert session._foreground is None
        assert ran == []

    async def test_a_dialog_on_another_loop_is_refused(self):
        with piped_session() as (session, inp):
            async with session:
                with pytest.raises(RuntimeError, match="run_coroutine_threadsafe"):
                    await self._on_a_threads_own_loop(lambda: session.yes_no_dialog("T", "B"))
                assert session._dialog_manager is None or not session._dialog_manager._visible

    async def test_a_call_handed_to_the_session_loop_from_a_thread_works(self):
        with piped_session() as (session, inp):
            async with session:
                loop = asyncio.get_running_loop()
                future = await asyncio.to_thread(
                    lambda: asyncio.run_coroutine_threadsafe(session.prompt_async(), loop)
                )
                await wait_until(lambda: waiting_for_input(session))
                inp.send_text("hi" + ENTER)
                assert await asyncio.wait_for(asyncio.wrap_future(future), 2) == "hi"


class TestRunAsyncHandlers:
    async def test_a_handler_can_ask_a_follow_up(self):
        from tests.test_end_to_end import run_with

        answers: list[str] = []

        async def handler(text: str) -> None:
            answers.append(await session.prompt_async())

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("question" + ENTER)
                await wait_until(lambda: session._foreground is not None and waiting_for_input(session))
                inp.send_text("answer" + ENTER)
                await wait_until(lambda: answers == ["answer"])

            await run_with(session, handler, script)


class TestConcurrent:
    async def test_tasks_run_beside_the_next_input(self):
        started: list[str] = []
        release = asyncio.Event()
        with piped_session() as (session, inp):

            async def respond(text: str) -> None:
                async with session.thinking(title=text) as box:
                    box.append(f"{text} working\n")
                    started.append(text)
                    await release.wait()

            async def body() -> None:
                jobs: set[asyncio.Task[None]] = set()
                while True:
                    try:
                        text = await session.prompt_async()
                    except (EOFError, KeyboardInterrupt):
                        break
                    job = asyncio.ensure_future(respond(text))
                    jobs.add(job)
                    job.add_done_callback(jobs.discard)
                for job in list(jobs):
                    job.cancel()

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("a" + ENTER)
                await wait_until(lambda: started == ["a"] and waiting_for_input(session))
                inp.send_text("b" + ENTER)
                await wait_until(lambda: started == ["a", "b"])
                assert session._manager.active_count == 2
                inp.send_text(CTRL_C)  # an idle prompt with live tasks' boxes
                await wait_until(lambda: session.status_text == session._BACKGROUND_STATUS)
                assert session._manager.active_count == 2
                release.set()
                await wait_until(lambda: session._manager.active_count == 0)
                texts = transcript_texts(session._display)
                assert "a working\n" in texts and "b working\n" in texts

            await run_loop(session, body, script)


class TestQueue:
    @staticmethod
    def _loop(session: ThinkingPromptSession, ran: list[str], started: list[str], release: asyncio.Event):
        async def respond(text: str) -> None:
            started.append(text)
            if text == "slow":
                await release.wait()
            ran.append(text)

        async def body() -> None:
            while True:
                try:
                    text = await session.prompt_async()
                except (EOFError, KeyboardInterrupt):
                    return
                await session.query(respond(text))

        return body

    def test_an_unknown_policy_is_refused(self):
        with pytest.raises(ValueError, match="input_while_busy must be 'refuse' or 'queue'"):
            ThinkingPromptSession(input_while_busy="drop")  # type: ignore[arg-type]

    async def test_refuse_keeps_the_draft_and_says_busy(self):
        ran: list[str] = []
        started: list[str] = []
        release = asyncio.Event()
        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("slow" + ENTER)
                await wait_until(lambda: started == ["slow"])
                inp.send_text("next" + ENTER)
                await wait_until(lambda: session.status_text == session._BUSY_STATUS)
                assert session._default_buffer.text == "next"
                assert not session._queued
                release.set()

            await run_loop(session, self._loop(session, ran, started, release), script)

    async def test_busy_outside_a_query_doesnt_offer_ctrl_c(self):
        # The loop awaits its work itself, not in query(): Ctrl+C has no
        # query to cancel (it would exit), so the hint doesn't offer it.
        started: list[str] = []
        release = asyncio.Event()
        with piped_session() as (session, inp):

            async def body() -> None:
                while True:
                    try:
                        text = await session.prompt_async()
                    except (EOFError, KeyboardInterrupt):
                        return
                    started.append(text)
                    await release.wait()

            async def script(run: asyncio.Task[None]) -> None:
                try:
                    inp.send_text("slow" + ENTER)
                    await wait_until(lambda: started == ["slow"])
                    inp.send_text("next" + ENTER)
                    await wait_until(lambda: session._hint is not None)
                    assert session.status_text == "Busy"
                    assert session._default_buffer.text == "next"
                finally:
                    release.set()  # the app stopping doesn't end the loop's own work

            await run_loop(session, body, script)

    async def _busy_loop(
        self,
        session: ThinkingPromptSession,
        started: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        """A loop that does its work itself, not in query(), in a box."""
        while True:
            try:
                await session.prompt_async()
            except (EOFError, KeyboardInterrupt):
                return
            async with session.thinking(title="work") as box:
                box.append("step 1\n")
                started.set()
                await release.wait()
                box.append("step 2\n")
            session.add_response("answer")

    async def test_ctrl_c_while_busy_outside_a_query_leaves_the_work_alone(self):
        """Nothing for Ctrl+C to stop: the loop's box is its live work, not
        a box nobody will end, and the typed draft stays."""
        started, release = asyncio.Event(), asyncio.Event()
        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                try:
                    inp.send_text("go" + ENTER)
                    await started.wait()
                    inp.send_text("draft" + CTRL_C)
                    await wait_until(lambda: session._hint is not None)
                    assert session.status_text == "Busy"
                    assert session.is_thinking
                    assert session._default_buffer.text == "draft"
                finally:
                    release.set()
                await wait_until(lambda: waiting_for_input(session))
                texts = transcript_texts(session._display)
                assert "Operation cancelled...\n" not in texts
                assert "step 1\nstep 2\n" in texts
                assert "answer" in texts[-1]

            await run_loop(session, lambda: self._busy_loop(session, started, release), script)

    async def test_ctrl_c_while_busy_outside_a_query_keeps_the_queued_lines(self):
        """Ctrl+C drops them with the query it stops: here it stops
        nothing, so they run next."""
        started, release = asyncio.Event(), asyncio.Event()
        with piped_session(input_while_busy="queue") as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                try:
                    inp.send_text("go" + ENTER)
                    await started.wait()
                    inp.send_text("next" + ENTER)
                    await wait_until(lambda: list(session._queued) == ["next"])
                    inp.send_text(CTRL_C)
                    await wait_until(lambda: session._hint is not None)
                    assert list(session._queued) == ["next"]
                finally:
                    release.set()
                await wait_until(lambda: echoed_inputs(session) == ["go", "next"])

            await run_loop(session, lambda: self._busy_loop(session, started, release), script)

    async def test_ctrl_d_while_busy_outside_a_query_doesnt_exit(self):
        """As Enter does, Ctrl+D finds the session busy: it exits once the
        loop waits for input again."""
        started, release = asyncio.Event(), asyncio.Event()
        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                try:
                    inp.send_text("go" + ENTER)
                    await started.wait()
                    inp.send_text(CTRL_D)
                    await wait_until(lambda: session._hint is not None)
                    assert session.status_text == "Busy"
                    assert session.app.is_running
                finally:
                    release.set()
                await wait_until(lambda: waiting_for_input(session))
                assert "answer" in transcript_texts(session._display)[-1]
                inp.send_text(CTRL_D)
                await finished(run)

            await run_loop(session, lambda: self._busy_loop(session, started, release), script)

    async def test_queued_lines_run_in_order_each_echoed_when_it_runs(self):
        ran: list[str] = []
        started: list[str] = []
        release = asyncio.Event()
        with piped_session(input_while_busy="queue") as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("slow" + ENTER)
                await wait_until(lambda: started == ["slow"])
                inp.send_text("two" + ENTER + "three" + ENTER)
                await wait_until(lambda: list(session._queued) == ["two", "three"])
                assert session._default_buffer.text == ""
                assert echoed_inputs(session) == ["slow"]
                await wait_until(lambda: any("queued: three" in line for line in screen_lines(session)))
                release.set()
                await wait_until(lambda: ran == ["slow", "two", "three"])
                assert echoed_inputs(session) == ["slow", "two", "three"]
                assert session._input_history.get_strings()[-3:] == ["slow", "two", "three"]

            await run_loop(session, self._loop(session, ran, started, release), script)

    @staticmethod
    def _queued_rows(session: ThinkingPromptSession) -> list[str]:
        return [line for line in screen_lines(session) if line.startswith(("queued:", "…"))]

    async def test_past_three_queued_lines_the_oldest_two_show_and_a_count(self):
        ran: list[str] = []
        started: list[str] = []
        release = asyncio.Event()
        with piped_session(input_while_busy="queue") as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("slow" + ENTER)
                await wait_until(lambda: started == ["slow"])
                inp.send_text("".join(f"line {i}" + ENTER for i in range(3)))
                await wait_until(lambda: len(self._queued_rows(session)) == 3)
                assert self._queued_rows(session) == ["queued: line 0", "queued: line 1", "queued: line 2"]
                inp.send_text("".join(f"line {i}" + ENTER for i in range(3, 5)))
                await wait_until(lambda: len(session._queued) == 5)
                await wait_until(lambda: "… 3 more queued" in self._queued_rows(session))
                assert self._queued_rows(session) == ["queued: line 0", "queued: line 1", "… 3 more queued"]
                release.set()

            await run_loop(session, self._loop(session, ran, started, release), script)

    async def test_a_long_queue_in_a_short_terminal_leaves_room_for_the_prompt(self):
        ran: list[str] = []
        started: list[str] = []
        release = asyncio.Event()
        with piped_session(rows=12, input_while_busy="queue") as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("slow" + ENTER)
                await wait_until(lambda: started == ["slow"])
                inp.send_text("".join(f"line {i}" + ENTER for i in range(20)))
                await wait_until(lambda: len(session._queued) == 20)
                session.app.invalidate()
                await wait_until(lambda: any("Window too small" in line or "more queued" in line
                                             for line in screen_lines(session)))
                lines = screen_lines(session)
                assert not any("Window too small" in line for line in lines), lines
                assert any(line.startswith(">>>") for line in lines), lines
                release.set()

            await run_loop(session, self._loop(session, ran, started, release), script)

    async def test_too_short_for_three_rows_the_queue_gives_way_to_the_prompt(self):
        ran: list[str] = []
        started: list[str] = []
        release = asyncio.Event()
        with piped_session(rows=5, input_while_busy="queue") as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("slow" + ENTER)
                await wait_until(lambda: started == ["slow"])
                inp.send_text("".join(f"line {i}" + ENTER for i in range(3)))
                await wait_until(lambda: len(session._queued) == 3)
                await wait_until(lambda: any(line.startswith(("queued:", "Window too small"))
                                             for line in screen_lines(session)))
                lines = screen_lines(session)
                assert not any("Window too small" in line for line in lines), lines
                assert any(line.startswith(">>>") for line in lines), lines
                release.set()

            await run_loop(session, self._loop(session, ran, started, release), script)

    async def test_has_queued_input_says_whether_a_line_waits(self):
        ran: list[str] = []
        started: list[str] = []
        release = asyncio.Event()
        with piped_session(input_while_busy="queue") as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                assert not session.has_queued_input
                inp.send_text("slow" + ENTER)
                await wait_until(lambda: started == ["slow"])
                inp.send_text("two" + ENTER + "three" + ENTER)
                await wait_until(lambda: list(session._queued) == ["two", "three"])
                assert session.has_queued_input
                inp.send_text(UP)  # "three" back to edit
                await wait_until(lambda: list(session._queued) == ["two"])
                assert session.has_queued_input
                release.set()
                await wait_until(lambda: ran == ["slow", "two"])
                assert not session.has_queued_input

            await run_loop(session, self._loop(session, ran, started, release), script)

    async def test_a_loop_can_take_every_queued_line_at_once(self):
        taken: list[str] = []
        release = asyncio.Event()
        with piped_session(input_while_busy="queue") as (session, inp):

            async def slow() -> None:
                await release.wait()

            async def body() -> None:
                await session.prompt_async()
                await session.query(slow())
                text = await session.prompt_async()
                while session.has_queued_input:
                    text += "\n" + await session.prompt_async()
                taken.append(text)

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: session._foreground is not None)
                inp.send_text("a" + ENTER + "b" + ENTER + "c" + ENTER)
                await wait_until(lambda: list(session._queued) == ["a", "b", "c"])
                release.set()
                await finished(run)
                assert taken == ["a\nb\nc"]
                assert echoed_inputs(session) == ["go", "a", "b", "c"]

            await run_loop(session, body, script)

    async def test_up_recalls_the_newest_queued_line(self):
        ran: list[str] = []
        started: list[str] = []
        release = asyncio.Event()
        with piped_session(input_while_busy="queue") as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("slow" + ENTER)
                await wait_until(lambda: started == ["slow"])
                inp.send_text("two" + ENTER + "three" + ENTER)
                await wait_until(lambda: list(session._queued) == ["two", "three"])
                inp.send_text(UP)
                await wait_until(lambda: session._default_buffer.text == "three")
                assert list(session._queued) == ["two"]
                release.set()
                await wait_until(lambda: ran == ["slow", "two"] and waiting_for_input(session))
                assert session._default_buffer.text == "three"

            await run_loop(session, self._loop(session, ran, started, release), script)

    async def test_a_follow_up_takes_the_oldest_queued_line(self):
        answers: list[str] = []
        release = asyncio.Event()
        with piped_session(input_while_busy="queue") as (session, inp):

            async def ask() -> None:
                await release.wait()
                answers.append(await session.prompt_async())

            async def body() -> None:
                await session.prompt_async()
                await session.query(ask())
                answers.append(await session.prompt_async())

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: session._foreground is not None)
                inp.send_text("yes" + ENTER + "next" + ENTER)
                await wait_until(lambda: list(session._queued) == ["yes", "next"])
                release.set()
                await wait_until(lambda: answers == ["yes", "next"])
                assert echoed_inputs(session) == ["go", "yes", "next"]

            await run_loop(session, body, script)

    async def test_blank_lines_are_not_queued(self):
        ran: list[str] = []
        started: list[str] = []
        release = asyncio.Event()
        with piped_session(input_while_busy="queue") as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("slow" + ENTER)
                await wait_until(lambda: started == ["slow"])
                inp.send_text("  " + ENTER)
                await asyncio.sleep(0.1)
                assert not session._queued
                release.set()

            await run_loop(session, self._loop(session, ran, started, release), script)

    async def test_ctrl_c_cancels_the_query_and_drops_the_queue(self):
        """Stop means stop: the lines queued behind the query don't start."""
        ran: list[str] = []
        started: list[str] = []
        release = asyncio.Event()
        with piped_session(input_while_busy="queue") as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("slow" + ENTER)
                await wait_until(lambda: started == ["slow"])
                inp.send_text("two" + ENTER)
                await wait_until(lambda: any("queued: two" in line for line in screen_lines(session)))
                inp.send_text(CTRL_C)
                await wait_until(lambda: waiting_for_input(session))
                assert not session._queued
                assert started == ["slow"] and ran == []
                assert echoed_inputs(session) == ["slow"]
                await wait_until(lambda: not any("queued:" in line for line in screen_lines(session)))

            await run_loop(session, self._loop(session, ran, started, release), script)

    async def test_exit_from_a_query_drops_the_lines_queued_behind_it(self):
        """The user typed "quit", then more: what follows quit doesn't run."""
        ran: list[str] = []
        release = asyncio.Event()
        with piped_session(input_while_busy="queue") as (session, inp):

            async def respond(text: str) -> None:
                ran.append(text)
                if text == "slow":
                    await release.wait()
                if text == "quit":
                    session.exit()

            async def body() -> None:
                while True:
                    try:
                        text = await session.prompt_async()
                    except (EOFError, KeyboardInterrupt):
                        return
                    await session.query(respond(text))

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("slow" + ENTER)
                await wait_until(lambda: ran == ["slow"])
                inp.send_text("quit" + ENTER + "after" + ENTER)
                await wait_until(lambda: list(session._queued) == ["quit", "after"])
                release.set()
                await finished(run)
                assert ran == ["slow", "quit"]
                assert echoed_inputs(session) == ["slow", "quit"]

            await run_loop(session, body, script)

    async def test_the_last_frame_leaves_out_the_queued_rows(self):
        """They're dropped at exit, so the scrollback doesn't keep them."""
        ran: list[str] = []
        started: list[str] = []
        release = asyncio.Event()
        with piped_session(input_while_busy="queue") as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("slow" + ENTER)
                await wait_until(lambda: started == ["slow"])
                inp.send_text("two" + ENTER)
                await wait_until(lambda: any("queued: two" in line for line in screen_lines(session)))
                assert not any("queued:" in line for line in done_frame(session))
                release.set()

            await run_loop(session, self._loop(session, ran, started, release), script)

    async def test_exit_drops_the_queue_unechoed(self):
        ran: list[str] = []
        started: list[str] = []
        release = asyncio.Event()
        with piped_session(input_while_busy="queue") as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("slow" + ENTER)
                await wait_until(lambda: started == ["slow"])
                inp.send_text("two" + ENTER)
                await wait_until(lambda: list(session._queued) == ["two"])
                session.exit()
                await finished(run)
                assert not session._queued
                assert echoed_inputs(session) == ["slow"]

            await run_loop(session, self._loop(session, ran, started, release), script)
        assert ran == []
