"""
Tests for ThinkingContext and session integration.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from thinking_prompt.types import StreamingContent, ThinkingContext


# =============================================================================
# ThinkingContext unit tests
# =============================================================================


class TestThinkingContextDelegation:
    """Test that ThinkingContext delegates to StreamingContent correctly."""

    def test_append_delegates(self):
        content = StreamingContent()
        ctx = ThinkingContext(content, set_title=MagicMock(), get_title=lambda: "")
        ctx.append("hello")
        assert content.text == "hello"

    def test_get_content_delegates(self):
        content = StreamingContent()
        content.append("hello")
        ctx = ThinkingContext(content, set_title=MagicMock(), get_title=lambda: "")
        assert ctx.get_content() == "hello"

    def test_clear_delegates(self):
        content = StreamingContent()
        content.append("hello")
        ctx = ThinkingContext(content, set_title=MagicMock(), get_title=lambda: "")
        ctx.clear()
        assert content.text == ""

    def test_set_line_delegates(self):
        content = StreamingContent()
        content.append("line0\nline1\n")
        ctx = ThinkingContext(content, set_title=MagicMock(), get_title=lambda: "")
        ctx.set_line(-1, "REPLACED")
        assert content.text == "line0\nREPLACED\n"

    def test_len_delegates(self):
        content = StreamingContent()
        content.append("a")
        content.append("b")
        ctx = ThinkingContext(content, set_title=MagicMock(), get_title=lambda: "")
        assert len(ctx) == 2

    def test_text_property_delegates(self):
        content = StreamingContent()
        content.append("hello")
        ctx = ThinkingContext(content, set_title=MagicMock(), get_title=lambda: "")
        assert ctx.text == "hello"


class TestThinkingContextTitleControl:
    """Test title control via ThinkingContext."""

    def test_set_title_calls_callback(self):
        setter = MagicMock()
        ctx = ThinkingContext(StreamingContent(), set_title=setter, get_title=lambda: "")
        ctx.set_title("Processing")
        setter.assert_called_once_with("Processing")

    def test_title_property_returns_via_getter(self):
        ctx = ThinkingContext(
            StreamingContent(),
            set_title=MagicMock(),
            get_title=lambda: "Current Title",
        )
        assert ctx.title == "Current Title"


class TestThinkingContextNoContent:
    """Test ThinkingContext when content is None (low-level API)."""

    def test_append_raises_without_content(self):
        ctx = ThinkingContext(None, set_title=MagicMock(), get_title=lambda: "")
        with pytest.raises(AttributeError, match="no content"):
            ctx.append("hello")

    def test_get_content_raises_without_content(self):
        ctx = ThinkingContext(None, set_title=MagicMock(), get_title=lambda: "")
        with pytest.raises(AttributeError, match="no content"):
            ctx.get_content()

    def test_clear_raises_without_content(self):
        ctx = ThinkingContext(None, set_title=MagicMock(), get_title=lambda: "")
        with pytest.raises(AttributeError, match="no content"):
            ctx.clear()

    def test_set_line_raises_without_content(self):
        ctx = ThinkingContext(None, set_title=MagicMock(), get_title=lambda: "")
        with pytest.raises(AttributeError, match="no content"):
            ctx.set_line(0, "x")

    def test_len_raises_without_content(self):
        ctx = ThinkingContext(None, set_title=MagicMock(), get_title=lambda: "")
        with pytest.raises(AttributeError, match="no content"):
            len(ctx)

    def test_text_raises_without_content(self):
        ctx = ThinkingContext(None, set_title=MagicMock(), get_title=lambda: "")
        with pytest.raises(AttributeError, match="no content"):
            _ = ctx.text

    def test_set_title_works_without_content(self):
        """Title control should work even when content is None."""
        setter = MagicMock()
        ctx = ThinkingContext(None, set_title=setter, get_title=lambda: "")
        ctx.set_title("Works")
        setter.assert_called_once_with("Works")


# =============================================================================
# Session integration tests
# =============================================================================


class TestSessionThinkingTitle:
    """Test thinking title integration in ThinkingPromptSession."""

    def _make_session(self):
        """Create a minimal session with app_info for separator."""
        from thinking_prompt import ThinkingPromptSession, AppInfo

        app_info = AppInfo(
            name="Test",
            version="0.0.1",
            thinking_text="Thinking",
        )
        return ThinkingPromptSession(app_info=app_info)

    def _make_session_no_appinfo(self):
        """Create a session without app_info (no separator)."""
        from thinking_prompt import ThinkingPromptSession
        return ThinkingPromptSession()

    def test_start_thinking_sets_title(self):
        session = self._make_session()
        session.start_thinking(lambda: "", title="Processing")
        assert session._thinking_separator.text == "Processing"
        session.finish_thinking(add_to_history=False, echo_to_console=False)

    def test_start_thinking_no_title_keeps_default(self):
        session = self._make_session()
        session.start_thinking(lambda: "")
        assert session._thinking_separator.text == "Thinking"
        session.finish_thinking(add_to_history=False, echo_to_console=False)

    def test_start_thinking_returns_thinking_context(self):
        session = self._make_session()
        ctx = session.start_thinking(lambda: "")
        assert isinstance(ctx, ThinkingContext)
        session.finish_thinking(add_to_history=False, echo_to_console=False)

    def test_finish_thinking_resets_title(self):
        session = self._make_session()
        session.start_thinking(lambda: "", title="Custom")
        assert session._thinking_separator.text == "Custom"
        session.finish_thinking(add_to_history=False, echo_to_console=False)
        assert session._thinking_separator.text == "Thinking"

    def test_set_title_via_context(self):
        session = self._make_session()
        ctx = session.start_thinking(lambda: "")
        ctx.set_title("Updated")
        assert session._thinking_separator.text == "Updated"
        session.finish_thinking(add_to_history=False, echo_to_console=False)

    def test_title_property_via_context(self):
        session = self._make_session()
        ctx = session.start_thinking(lambda: "", title="Hello")
        assert ctx.title == "Hello"
        session.finish_thinking(add_to_history=False, echo_to_console=False)

    def test_no_separator_no_error(self):
        """Session without app_info should not error on title operations."""
        session = self._make_session_no_appinfo()
        ctx = session.start_thinking(lambda: "", title="Ignored")
        ctx.set_title("Also Ignored")
        assert ctx.title == "Thinking"  # default fallback
        session.finish_thinking(add_to_history=False, echo_to_console=False)

    @pytest.mark.asyncio
    async def test_thinking_context_manager_title(self):
        session = self._make_session()
        async with session.thinking(title="Working", add_to_history=False, echo_to_console=False) as ctx:
            assert session._thinking_separator.text == "Working"
            ctx.set_title("Almost Done")
            assert session._thinking_separator.text == "Almost Done"
        # After exit, title should be reset
        assert session._thinking_separator.text == "Thinking"

    @pytest.mark.asyncio
    async def test_thinking_context_manager_resets_on_exception(self):
        session = self._make_session()
        with pytest.raises(ValueError):
            async with session.thinking(title="Crashing", add_to_history=False, echo_to_console=False) as ctx:
                assert session._thinking_separator.text == "Crashing"
                raise ValueError("boom")
        # Title should still be reset
        assert session._thinking_separator.text == "Thinking"

    @pytest.mark.asyncio
    async def test_thinking_context_manager_yields_thinking_context(self):
        session = self._make_session()
        async with session.thinking(add_to_history=False, echo_to_console=False) as ctx:
            assert isinstance(ctx, ThinkingContext)
            ctx.append("hello\n")
            assert ctx.text == "hello\n"

    @pytest.mark.asyncio
    async def test_thinking_context_set_line_integration(self):
        """set_line via ThinkingContext inside context manager."""
        session = self._make_session()
        async with session.thinking(add_to_history=False, echo_to_console=False) as ctx:
            ctx.append("line0\nline1\n")
            ctx.set_line(-1, "UPDATED")
            assert ctx.text == "line0\nUPDATED\n"
