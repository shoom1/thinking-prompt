"""Tests for ThinkingPromptSession handler lifecycle.

Covers three review findings:
1. Ctrl+C must actually cancel the running handler — not just remove
   thinking boxes.
2. Input submitted while a handler is running must not be silently
   dropped (echoed + cleared but never delivered).
3. Handler exceptions must clean up any thinking boxes the handler
   opened, so the UI doesn't get stuck in "thinking" state.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from thinking_prompt import ThinkingPromptSession


@pytest.fixture
def session() -> ThinkingPromptSession:
    """A bare session — no app running, just enough state for unit tests."""
    return ThinkingPromptSession()


class TestRunHandler:
    """_run_handler is the cancellable wrapper around a user input handler."""

    async def test_async_handler_tracked_and_cleared(self, session):
        gate = asyncio.Event()
        running_event = asyncio.Event()

        async def handler(text: str) -> None:
            running_event.set()
            await gate.wait()

        run_task = asyncio.create_task(session._run_handler(handler, "hello"))

        # Wait until the handler is actually running, then verify the
        # session exposes the in-flight task.
        await asyncio.wait_for(running_event.wait(), timeout=1)
        assert session._current_handler_task is not None
        assert not session._current_handler_task.done()

        gate.set()
        await run_task
        assert session._current_handler_task is None

    async def test_sync_handler_does_not_set_task(self, session):
        called = []

        def handler(text: str) -> None:
            called.append(text)
            # Sync handler completes synchronously; no task should be tracked.
            assert session._current_handler_task is None

        await session._run_handler(handler, "hi")
        assert called == ["hi"]
        assert session._current_handler_task is None

    async def test_handler_exception_finishes_active_boxes(self, session):
        async def handler(text: str) -> None:
            session.start_thinking(lambda: "in progress\n", title="Work")
            raise RuntimeError("boom")

        # has_active_boxes will be False after _run_handler returns.
        await session._run_handler(handler, "go")
        assert session._manager.has_active_boxes is False
        assert session._current_handler_task is None

    async def test_user_cancel_finishes_active_boxes_and_does_not_propagate(
        self, session
    ):
        """Ctrl+C path: external code sets _user_cancelled_handler and
        cancels the task. _run_handler must absorb the CancelledError so
        the input loop continues to the next prompt."""
        gate = asyncio.Event()

        async def handler(text: str) -> None:
            session.start_thinking(lambda: "running\n", title="Work")
            await gate.wait()

        run_task = asyncio.create_task(session._run_handler(handler, "go"))

        # Wait for the handler task to register.
        for _ in range(20):
            await asyncio.sleep(0)
            if session._current_handler_task is not None:
                break
        assert session._current_handler_task is not None

        # Simulate Ctrl+C: mark as user cancellation, then cancel.
        session._user_cancelled_handler = True
        session._current_handler_task.cancel()

        # _run_handler should swallow the CancelledError.
        await run_task

        assert session._manager.has_active_boxes is False
        assert session._current_handler_task is None
        assert session._user_cancelled_handler is False

    async def test_outer_cancel_propagates(self, session):
        """If the surrounding input_loop is cancelled (not Ctrl+C), the
        CancelledError must propagate so the loop exits cleanly."""
        gate = asyncio.Event()

        async def handler(text: str) -> None:
            await gate.wait()

        run_task = asyncio.create_task(session._run_handler(handler, "go"))

        for _ in range(20):
            await asyncio.sleep(0)
            if session._current_handler_task is not None:
                break

        # No _user_cancelled_handler flag set: this is an external cancel.
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task


class TestAcceptHandlerWhileBusy:
    """The default_buffer's accept_handler must not deliver input while a
    handler is running — otherwise the new input is echoed + cleared but
    never reaches the handler."""

    def test_idle_session_delivers_input(self, session):
        """Sanity check: with no handler running, input flows normally."""
        # Create a fake pending input future.
        loop = asyncio.new_event_loop()
        try:
            session._pending_input = loop.create_future()
            session.default_buffer.text = "hello"

            accepted = session.default_buffer.validation_state  # baseline access
            ah = session.default_buffer.accept_handler
            assert ah is not None

            result = ah(session.default_buffer)
            assert result is True
            assert session._pending_input.done()
            assert session._pending_input.result() == "hello"
        finally:
            loop.close()

    def test_busy_session_drops_input(self, session):
        """While a handler task is running, accept_handler refuses the
        input (returns False, leaves buffer intact, does not resolve the
        pending input future)."""
        loop = asyncio.new_event_loop()
        try:
            # Simulate a running handler.
            async def _noop():
                await asyncio.sleep(3600)

            running = loop.create_task(_noop())
            session._current_handler_task = running

            session._pending_input = loop.create_future()
            session.default_buffer.text = "queued"

            ah = session.default_buffer.accept_handler
            assert ah is not None
            result = ah(session.default_buffer)

            # Don't deliver the text and don't clear the buffer.
            assert session._pending_input.done() is False
            assert session.default_buffer.text == "queued"
            # Falsy return tells prompt_toolkit to keep the buffer.
            assert result is False

            running.cancel()
            try:
                loop.run_until_complete(running)
            except asyncio.CancelledError:
                pass
        finally:
            loop.close()


class TestCtrlCKeyBinding:
    """The Ctrl+C key binding must cancel the handler task in addition to
    finishing active thinking boxes."""

    def _get_ctrl_c_handler(self, session):
        from prompt_toolkit.keys import Keys
        kb = session.app.key_bindings
        for binding in kb.bindings:
            if binding.keys == (Keys.ControlC,):
                return binding.handler
        raise AssertionError("Ctrl+C binding not registered")

    def test_ctrl_c_cancels_running_handler(self, session):
        """When a handler task is running, Ctrl+C marks it as user-cancelled
        and calls .cancel() on it."""
        loop = asyncio.new_event_loop()
        try:
            async def _noop():
                await asyncio.sleep(3600)

            running = loop.create_task(_noop())
            session._current_handler_task = running

            handler = self._get_ctrl_c_handler(session)
            event = MagicMock()
            event.app = session.app
            handler(event)

            assert session._user_cancelled_handler is True
            assert running.cancelled() or running._must_cancel is True
        finally:
            try:
                loop.run_until_complete(running)
            except (asyncio.CancelledError, RuntimeError):
                pass
            loop.close()

    def test_ctrl_c_idle_exits_app(self, session):
        """With no handler and no boxes, Ctrl+C exits the application."""
        handler = self._get_ctrl_c_handler(session)
        event = MagicMock()
        # No handler task, no active boxes.
        session._current_handler_task = None
        handler(event)
        event.app.exit.assert_called_once()

    def test_ctrl_c_with_orphan_box_clears_box_and_does_not_exit(self, session):
        """Ctrl+C with an active thinking box (and no handler) must clear
        the box but not also exit the app. Previously the binding read
        has_active_boxes after finish_all() and treated the now-empty
        manager as 'idle', falling through to app.exit()."""
        # Open a box without a handler — simulates a box left orphaned by
        # earlier code, or a box opened from a non-handler context.
        session.start_thinking(lambda: "stuck", title="Stuck")
        assert session._manager.has_active_boxes is True

        handler = self._get_ctrl_c_handler(session)
        event = MagicMock()
        event.app = MagicMock()
        handler(event)

        assert session._manager.has_active_boxes is False
        event.app.exit.assert_not_called()


class TestUserCancelledFlagReset:
    """_user_cancelled_handler must not stay True after _run_handler returns.

    A sticky flag means the next outer cancellation (e.g. shutdown) is
    silently swallowed because _run_handler treats it as a Ctrl+C."""

    async def test_flag_reset_when_handler_swallows_cancel(self, session):
        """If user code catches CancelledError and returns normally, the
        flag must still be cleared so the next handler starts clean.

        We use a `started` event so the cancel arrives *while the handler
        is awaiting its gate*, not before its body has run — otherwise the
        task is cancelled before its first tick and the outer await raises
        CancelledError, hiding the bug we want to catch."""
        started = asyncio.Event()
        gate = asyncio.Event()

        async def handler(text: str) -> None:
            started.set()
            try:
                await gate.wait()
            except asyncio.CancelledError:
                # User code intentionally swallows — no re-raise. The outer
                # `await task` inside _run_handler returns normally (no
                # CancelledError), so the except block that resets the flag
                # is never entered.
                return

        run_task = asyncio.create_task(session._run_handler(handler, "go"))

        # Wait until the handler is actually running before issuing cancel.
        await asyncio.wait_for(started.wait(), timeout=1)
        assert session._current_handler_task is not None

        session._user_cancelled_handler = True
        session._current_handler_task.cancel()
        await run_task

        # After _run_handler returns the flag MUST be reset, regardless of
        # whether the inner task raised CancelledError or returned normally.
        assert session._user_cancelled_handler is False
        assert session._current_handler_task is None

    async def test_flag_reset_when_cancel_loses_race_to_completion(self, session):
        """If Ctrl+C cancel is set but the task completes naturally before
        cancellation takes effect, the flag must still reset for the next
        handler invocation."""

        async def handler(text: str) -> None:
            return  # finishes immediately, no chance to be cancelled

        session._user_cancelled_handler = True  # left over from prior cycle
        await session._run_handler(handler, "go")

        assert session._user_cancelled_handler is False
        assert session._current_handler_task is None

    async def test_outer_cancel_after_user_swallow_propagates(self, session):
        """End-to-end: user cancel + handler swallow + later outer cancel
        on a fresh handler must propagate (not be swallowed) because the
        flag has been reset."""

        async def swallowing(text: str) -> None:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                return  # swallowed

        run1 = asyncio.create_task(session._run_handler(swallowing, "first"))
        for _ in range(50):
            await asyncio.sleep(0)
            if session._current_handler_task is not None:
                break
        session._user_cancelled_handler = True
        session._current_handler_task.cancel()
        await run1
        assert session._user_cancelled_handler is False

        # Now a fresh handler — outer cancellation must propagate.
        async def long_running(text: str) -> None:
            await asyncio.sleep(3600)

        run2 = asyncio.create_task(session._run_handler(long_running, "second"))
        for _ in range(50):
            await asyncio.sleep(0)
            if session._current_handler_task is not None:
                break

        run2.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run2
