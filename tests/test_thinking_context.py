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


class TestThinkingContextFinish:
    """Test ThinkingContext.finish() method."""

    def test_finish_calls_callback(self):
        finish_mock = MagicMock(return_value="content")
        ctx = ThinkingContext(
            StreamingContent(),
            set_title=MagicMock(),
            get_title=lambda: "",
            finish=finish_mock,
        )
        result = ctx.finish()
        finish_mock.assert_called_once_with(add_to_history=True, echo_to_console=None)
        assert result == "content"

    def test_finish_passes_kwargs(self):
        finish_mock = MagicMock(return_value="content")
        ctx = ThinkingContext(
            StreamingContent(),
            set_title=MagicMock(),
            get_title=lambda: "",
            finish=finish_mock,
        )
        ctx.finish(add_to_history=False, echo_to_console=True)
        finish_mock.assert_called_once_with(add_to_history=False, echo_to_console=True)

    def test_finish_raises_without_callback(self):
        ctx = ThinkingContext(
            StreamingContent(),
            set_title=MagicMock(),
            get_title=lambda: "",
        )
        with pytest.raises(RuntimeError, match="No finish callback"):
            ctx.finish()

    def test_finish_works_without_content(self):
        """finish() should work even when content is None (low-level API)."""
        finish_mock = MagicMock(return_value="")
        ctx = ThinkingContext(
            None,
            set_title=MagicMock(),
            get_title=lambda: "",
            finish=finish_mock,
        )
        ctx.finish()
        finish_mock.assert_called_once()


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
        ctx = session.start_thinking(lambda: "", title="Processing")
        assert ctx.title == "Processing"
        session.finish_thinking(add_to_history=False, echo_to_console=False)

    def test_start_thinking_no_title_keeps_default(self):
        session = self._make_session()
        ctx = session.start_thinking(lambda: "")
        assert ctx.title == "Thinking"  # default
        session.finish_thinking(add_to_history=False, echo_to_console=False)

    def test_start_thinking_returns_thinking_context(self):
        session = self._make_session()
        ctx = session.start_thinking(lambda: "")
        assert isinstance(ctx, ThinkingContext)
        session.finish_thinking(add_to_history=False, echo_to_console=False)

    def test_set_title_via_context(self):
        session = self._make_session()
        ctx = session.start_thinking(lambda: "")
        ctx.set_title("Updated")
        assert ctx.title == "Updated"
        session.finish_thinking(add_to_history=False, echo_to_console=False)

    def test_title_property_via_context(self):
        session = self._make_session()
        ctx = session.start_thinking(lambda: "", title="Hello")
        assert ctx.title == "Hello"
        session.finish_thinking(add_to_history=False, echo_to_console=False)

    def test_no_title_no_error(self):
        """Session without title should use default fallback."""
        session = self._make_session_no_appinfo()
        ctx = session.start_thinking(lambda: "")
        assert ctx.title == "Thinking"  # default fallback
        session.finish_thinking(add_to_history=False, echo_to_console=False)

    @pytest.mark.asyncio
    async def test_thinking_context_manager_title(self):
        session = self._make_session()
        async with session.thinking(title="Working", add_to_history=False, echo_to_console=False) as ctx:
            assert ctx.title == "Working"
            ctx.set_title("Almost Done")
            assert ctx.title == "Almost Done"

    @pytest.mark.asyncio
    async def test_thinking_context_manager_resets_on_exception(self):
        session = self._make_session()
        with pytest.raises(ValueError):
            async with session.thinking(title="Crashing", add_to_history=False, echo_to_console=False) as ctx:
                assert ctx.title == "Crashing"
                raise ValueError("boom")
        # After exception, the box should be removed
        assert not session._manager.has_active_boxes

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


# =============================================================================
# ThinkingContext Rich methods tests
# =============================================================================


class TestThinkingContextRichMethods:
    """Test append_rich() and set_line_rich() on ThinkingContext."""

    def test_append_rich_converts_markup(self):
        """append_rich should convert Rich markup and append."""
        content = StreamingContent()
        set_format_calls = []
        ctx = ThinkingContext(
            content,
            set_title=MagicMock(),
            get_title=lambda: "",
            set_format=lambda fmt: set_format_calls.append(fmt),
        )
        ctx.append_rich("[green]✓ Done[/green]\n")
        text = content.text
        assert "✓ Done" in text
        assert "\033[" in text  # ANSI codes

    def test_append_rich_auto_switches_format(self):
        """append_rich should auto-switch to ansi format."""
        content = StreamingContent()
        set_format_calls = []
        ctx = ThinkingContext(
            content,
            set_title=MagicMock(),
            get_title=lambda: "",
            set_format=lambda fmt: set_format_calls.append(fmt),
        )
        ctx.append_rich("[bold]text[/bold]")
        assert set_format_calls == ["ansi"]

    def test_set_line_rich_auto_switches_format(self):
        """set_line_rich should auto-switch to ansi format."""
        content = StreamingContent()
        content.append("line0\nline1\n")
        set_format_calls = []
        ctx = ThinkingContext(
            content,
            set_title=MagicMock(),
            get_title=lambda: "",
            set_format=lambda fmt: set_format_calls.append(fmt),
        )
        ctx.set_line_rich(0, "[green]✓ line0[/green]")
        assert set_format_calls == ["ansi"]

    def test_set_line_rich_replaces_line(self):
        """set_line_rich should replace the specified line."""
        content = StreamingContent()
        content.append("line0\nline1\n")
        ctx = ThinkingContext(
            content,
            set_title=MagicMock(),
            get_title=lambda: "",
            set_format=MagicMock(),
        )
        ctx.set_line_rich(0, "[green]REPLACED[/green]")
        text = content.text
        assert "REPLACED" in text
        assert "line1" in text

    def test_append_rich_without_set_format(self):
        """append_rich should work even without set_format callback."""
        content = StreamingContent()
        ctx = ThinkingContext(
            content,
            set_title=MagicMock(),
            get_title=lambda: "",
        )
        ctx.append_rich("[bold]text[/bold]")
        assert "text" in content.text

    def test_append_rich_raises_without_content(self):
        """append_rich should raise when content is None."""
        ctx = ThinkingContext(
            None,
            set_title=MagicMock(),
            get_title=lambda: "",
        )
        with pytest.raises(AttributeError, match="no content"):
            ctx.append_rich("[bold]text[/bold]")

    def test_set_line_rich_raises_without_content(self):
        """set_line_rich should raise when content is None."""
        ctx = ThinkingContext(
            None,
            set_title=MagicMock(),
            get_title=lambda: "",
        )
        with pytest.raises(AttributeError, match="no content"):
            ctx.set_line_rich(0, "[bold]text[/bold]")

    def test_rich_theme_is_passed_through(self):
        """rich_theme should be used when no explicit theme is given."""
        from rich.theme import Theme
        custom_theme = Theme({"custom": "bold green"})

        content = StreamingContent()
        ctx = ThinkingContext(
            content,
            set_title=MagicMock(),
            get_title=lambda: "",
            set_format=MagicMock(),
            rich_theme=custom_theme,
        )
        ctx.append_rich("[custom]styled[/custom]")
        text = content.text
        # Should contain the text (with ANSI styling from theme)
        assert "styled" in text


class TestThinkingContextRichSessionIntegration:
    """Test Rich methods through session.thinking() context manager."""

    def _make_session(self):
        from thinking_prompt import ThinkingPromptSession, AppInfo
        app_info = AppInfo(
            name="Test",
            version="0.0.1",
            thinking_text="Thinking",
        )
        return ThinkingPromptSession(app_info=app_info)

    @pytest.mark.asyncio
    async def test_append_rich_in_context_manager(self):
        """append_rich should work inside thinking() context manager."""
        session = self._make_session()
        async with session.thinking(add_to_history=False, echo_to_console=False) as ctx:
            ctx.append_rich("[green]✓ Step 1[/green]\n")
            ctx.append_rich("[dim]  Step 2[/dim]\n")
            text = ctx.text
            assert "✓ Step 1" in text
            assert "Step 2" in text

    @pytest.mark.asyncio
    async def test_set_line_rich_in_context_manager(self):
        """set_line_rich should work inside thinking() context manager."""
        session = self._make_session()
        async with session.thinking(add_to_history=False, echo_to_console=False) as ctx:
            ctx.append_rich("[dim]  Step 1[/dim]\n")
            ctx.append_rich("[dim]  Step 2[/dim]\n")
            ctx.set_line_rich(0, "[green]✓ Step 1[/green]")
            text = ctx.text
            assert "✓ Step 1" in text

    @pytest.mark.asyncio
    async def test_append_rich_auto_switches_format_in_session(self):
        """append_rich should auto-switch thinking control to ansi format."""
        session = self._make_session()
        async with session.thinking(add_to_history=False, echo_to_console=False) as ctx:
            # Verify through the manager's box
            boxes = session._manager.get_sorted_boxes()
            assert len(boxes) == 1
            assert boxes[0].control.content_format == "plain"
            ctx.append_rich("[bold]text[/bold]")
            assert boxes[0].control.content_format == "ansi"
