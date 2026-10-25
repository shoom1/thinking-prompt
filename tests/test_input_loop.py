"""The pull loop: ``async with session:`` runs the app, ``prompt_async()``
reads an input, ``query()`` runs one input's work as the query Ctrl+C
cancels."""
from __future__ import annotations

import asyncio
import inspect
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

    async def test_ctrl_c_at_an_idle_prompt_raises_keyboard_interrupt(self):
        raised: list[str] = []
        with piped_session() as (session, inp):

            async def body() -> None:
                try:
                    await session.prompt_async()
                except KeyboardInterrupt:
                    raised.append("interrupt")

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text(CTRL_C)
                await finished(run)

            await run_loop(session, body, script)
        assert raised == ["interrupt"]

    async def test_a_second_waiter_is_refused(self):
        with piped_session() as (session, inp):

            async def body() -> None:
                first = asyncio.ensure_future(session.prompt_async())
                await wait_until(lambda: waiting_for_input(session))
                with pytest.raises(RuntimeError, match="already waiting"):
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

    async def test_ctrl_d_cancels_the_query_and_the_loop_ends(self):
        results: list[object] = []
        started: list[str] = []
        with piped_session() as (session, inp):

            async def body() -> None:
                text = await session.prompt_async()
                results.append(await session.query(forever(session, text, started)))
                with pytest.raises(EOFError):
                    await session.prompt_async()

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("go" + ENTER)
                await wait_until(lambda: started == ["go"])
                inp.send_text(CTRL_D)
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
    """Ctrl+D while a query asks a follow-up ends the query as the app
    stopping does: it's cancelled, not given an EOFError to raise."""

    async def test_the_query_returns_none_and_the_loop_ends(self):
        results: list[object] = []
        with piped_session() as (session, inp):

            async def respond() -> str:
                return await session.prompt_async()

            async def body() -> None:
                await session.prompt_async()
                results.append(await session.query(respond()))
                with pytest.raises(EOFError):
                    await session.prompt_async()

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("question" + ENTER)
                await wait_until(lambda: session._foreground is not None and waiting_for_input(session))
                inp.send_text(CTRL_D)
                await finished(run)

            await run_loop(session, body, script)
        assert results == [None]

    async def test_a_handler_asking_ends_without_an_error(self):
        from tests.test_end_to_end import run_with

        async def handler(text: str) -> None:
            await session.prompt_async()

        with piped_session() as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("question" + ENTER)
                await wait_until(lambda: session._foreground is not None and waiting_for_input(session))
                inp.send_text(CTRL_D)
                await finished(run)
                assert not any("Handler error" in text for text in transcript_texts(session._display))

            await run_with(session, handler, script)


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

    async def test_ctrl_c_cancels_the_query_and_the_queue_runs(self):
        ran: list[str] = []
        started: list[str] = []
        release = asyncio.Event()
        with piped_session(input_while_busy="queue") as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                inp.send_text("slow" + ENTER)
                await wait_until(lambda: started == ["slow"])
                inp.send_text("two" + ENTER)
                await wait_until(lambda: list(session._queued) == ["two"])
                inp.send_text(CTRL_C)
                await wait_until(lambda: ran == ["two"])

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
                inp.send_text(CTRL_D)
                await finished(run)
                assert not session._queued
                assert echoed_inputs(session) == ["slow"]

            await run_loop(session, self._loop(session, ran, started, release), script)
        assert ran == []
