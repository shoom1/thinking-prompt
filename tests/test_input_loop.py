"""The pull loop: ``async with session:`` runs the app, ``prompt_async()``
reads an input, ``query()`` runs one input's work as the query Ctrl+C
cancels."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from contextlib import suppress
from typing import Callable

import pytest

from tests.helpers import transcript_texts
from tests.test_end_to_end import (
    CTRL_C,
    CTRL_D,
    ENTER,
    echoed_inputs,
    piped_session,
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
