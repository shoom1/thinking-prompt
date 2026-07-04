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


def _get_ctrl_c_handler(session: ThinkingPromptSession):
    """Find the Ctrl+C key binding handler on the session's app."""
    from prompt_toolkit.keys import Keys

    kb = session.app.key_bindings
    for binding in kb.bindings:
        if binding.keys == (Keys.ControlC,):
            return binding.handler
    raise AssertionError("Ctrl+C binding not registered")


def _get_ctrl_d_binding(session: ThinkingPromptSession):
    """Find the Ctrl+D key binding (handler + filter) on the session's app."""
    from prompt_toolkit.keys import Keys

    kb = session.app.key_bindings
    for binding in kb.bindings:
        if binding.keys == (Keys.ControlD,):
            return binding
    raise AssertionError("Ctrl+D binding not registered")


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

    async def test_async_handler_success_finishes_orphan_boxes(self, session):
        """A handler that returns without finishing its box must not leave
        the UI stuck in a 'thinking' state — _run_handler's docstring
        promises cleanup on completion, not only on error/cancel."""

        async def handler(text: str) -> None:
            session.start_thinking(lambda: "orphan\n", title="Work")
            # returns without ctx.finish()

        await session._run_handler(handler, "go")
        assert session._manager.has_active_boxes is False
        assert session._current_handler_task is None

    async def test_sync_handler_finishes_orphan_boxes(self, session):
        """Same contract for sync handlers: the early-return path must
        also drop leftover boxes."""

        def handler(text: str) -> None:
            session.start_thinking(lambda: "orphan\n", title="Work")

        await session._run_handler(handler, "go")
        assert session._manager.has_active_boxes is False

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
        return _get_ctrl_c_handler(session)

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

    async def test_ctrl_c_idle_exits_app(self, session):
        """With no handler and no boxes, Ctrl+C exits the application.

        At a real idle prompt, prompt_async() has installed a live
        _pending_input future — its mere existence must not suppress the
        exit. (The earlier version of this test set _pending_input = None,
        a state that never occurs at an idle prompt in a real run, which
        is how the zombie-session bug slipped past.)"""
        session._pending_input = asyncio.get_running_loop().create_future()
        session._current_handler_task = None

        handler = self._get_ctrl_c_handler(session)
        event = MagicMock()
        handler(event)

        # The pending future is cancelled (direct prompt_async callers get
        # KeyboardInterrupt) AND the app exits on this first Ctrl+C.
        assert session._pending_input.cancelled()
        event.app.exit.assert_called_once()

    async def test_first_ctrl_c_at_idle_prompt_terminates_run_async(self):
        """Regression: the first Ctrl+C at an idle prompt must end the
        session. Previously the binding treated the live pending-input
        future as in-flight work — it cancelled the future (killing the
        input loop) but never called app.exit(), leaving a zombie app
        that echoed typed input without ever delivering it."""
        session = ThinkingPromptSession()

        # Grab the real Ctrl+C binding before stubbing out the app.
        ctrl_c = _get_ctrl_c_handler(session)

        # Stub the Application: run_async blocks until exit() is called,
        # like the real one — but without a terminal.
        exited = asyncio.Event()

        async def fake_run_async() -> None:
            await exited.wait()

        app = MagicMock()
        app.run_async = fake_run_async
        app.exit = MagicMock(side_effect=exited.set)
        app.is_running = True
        session.app = app

        async def handler(text: str) -> None:
            pass

        run_task = asyncio.create_task(session.run_async(handler))

        # Wait until the input loop reaches the idle prompt (live future).
        for _ in range(100):
            await asyncio.sleep(0)
            if (
                session._pending_input is not None
                and not session._pending_input.done()
            ):
                break
        assert session._pending_input is not None
        assert not session._pending_input.done()

        # One Ctrl+C — the session must terminate, not become a zombie.
        event = MagicMock()
        event.app = app
        ctrl_c(event)

        await asyncio.wait_for(run_task, timeout=1)
        app.exit.assert_called_once()

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


class TestCtrlDKeyBinding:
    """Ctrl+D must deliver the documented EOFError to prompt_async()
    callers and must not fire while the input line has text."""

    async def test_ctrl_d_sets_eoferror_on_pending_input(self, session):
        """prompt_async() docstring: 'Raises EOFError when Ctrl+D is
        pressed'. The binding must resolve the pending future, not just
        exit the app (which left direct prompt_async callers hanging)."""
        session._pending_input = asyncio.get_running_loop().create_future()

        binding = _get_ctrl_d_binding(session)
        event = MagicMock()
        binding.handler(event)

        event.app.exit.assert_called_once()
        assert session._pending_input.done()
        with pytest.raises(EOFError):
            session._pending_input.result()

    def test_ctrl_d_filter_false_when_buffer_has_text(self, session):
        """Readline semantics: EOF only on an empty line. With a draft in
        the buffer the binding must not be active (the default emacs
        delete-char binding applies instead), so Ctrl+D can't destroy
        typed input and kill the session."""
        binding = _get_ctrl_d_binding(session)

        session.default_buffer.text = "draft in progress"
        assert not binding.filter()

        session.default_buffer.reset()
        assert binding.filter()

    async def test_prompt_async_raises_eoferror_end_to_end(self, session):
        """await prompt_async() must raise EOFError after Ctrl+D."""
        prompt_task = asyncio.create_task(session.prompt_async())
        # Let prompt_async install its future.
        for _ in range(20):
            await asyncio.sleep(0)
            if session._pending_input is not None and not session._pending_input.done():
                break

        binding = _get_ctrl_d_binding(session)
        event = MagicMock()
        binding.handler(event)

        with pytest.raises(EOFError):
            await prompt_task


class TestSessionClear:
    """clear() must clear the screen via the renderer while the app is
    running — a raw escape write behind the renderer's back leaves its
    notion of the screen stale and corrupts the next repaint."""

    def test_clear_uses_renderer_when_app_running(self, session, capsys):
        session.app = MagicMock()
        session.app.is_running = True
        session._display.response("hello")
        capsys.readouterr()  # discard the echoed response

        session.clear()

        session.app.renderer.clear.assert_called_once()
        assert "\033[2J" not in capsys.readouterr().out
        assert session._display.history.is_empty

    def test_clear_falls_back_to_escape_codes_when_not_running(
        self, session, capsys
    ):
        session.app = MagicMock()
        session.app.is_running = False

        session.clear()

        session.app.renderer.clear.assert_not_called()
        assert "\033[2J" in capsys.readouterr().out


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
