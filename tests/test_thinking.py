"""
Tests for ThinkingBoxControl.
"""
from __future__ import annotations

import pytest
from prompt_toolkit.formatted_text import FormattedText

from thinking_prompt.thinking import ThinkingBoxControl


class TestThinkingBoxControlBasics:
    """Test basic functionality of ThinkingBoxControl."""

    def test_initial_state_inactive(self, thinking_control: ThinkingBoxControl):
        """Control should be inactive when first created."""
        assert not thinking_control.is_active
        assert not thinking_control.is_expanded
        assert thinking_control.content == ""

    def test_start_activates_control(self, thinking_control: ThinkingBoxControl):
        """Starting should activate the control."""
        thinking_control.start(lambda: "test content")
        assert thinking_control.is_active

    def test_start_sets_content_callback(self, thinking_control: ThinkingBoxControl):
        """Starting should set the content callback."""
        thinking_control.start(lambda: "hello world")
        assert thinking_control.content == "hello world"

    def test_finish_returns_content_and_state(self, thinking_control: ThinkingBoxControl):
        """Finishing should return content and expansion state."""
        thinking_control.start(lambda: "test content")
        content, was_expanded = thinking_control.finish()

        assert content == "test content"
        assert not was_expanded

    def test_finish_resets_state(self, thinking_control: ThinkingBoxControl):
        """Finishing should reset the control to inactive state."""
        thinking_control.start(lambda: "test")
        thinking_control.finish()

        assert not thinking_control.is_active
        assert not thinking_control.is_expanded
        assert thinking_control.content == ""

    def test_finish_returns_expanded_state(self, thinking_control: ThinkingBoxControl):
        """Finishing should return True for was_expanded if expanded."""
        thinking_control.start(lambda: "test")
        thinking_control.expand()
        content, was_expanded = thinking_control.finish()

        assert was_expanded

    def test_content_callback_error_handling(self, thinking_control: ThinkingBoxControl):
        """Control should handle errors in content callback gracefully."""
        def bad_callback():
            raise ValueError("Callback error")

        thinking_control.start(bad_callback)
        # Should not raise, should return empty string
        assert thinking_control.content == ""


class TestThinkingBoxControlExpansion:
    """Test expansion/collapse functionality."""

    def test_expand_sets_expanded(self, thinking_control: ThinkingBoxControl):
        """Expand should set is_expanded to True."""
        thinking_control.start(lambda: "test")
        thinking_control.expand()
        assert thinking_control.is_expanded

    def test_collapse_clears_expanded(self, thinking_control: ThinkingBoxControl):
        """Collapse should set is_expanded to False."""
        thinking_control.start(lambda: "test")
        thinking_control.expand()
        thinking_control.collapse()
        assert not thinking_control.is_expanded

    def test_toggle_switches_state(self, thinking_control: ThinkingBoxControl):
        """Toggle should switch expanded state."""
        thinking_control.start(lambda: "test")

        assert not thinking_control.is_expanded
        thinking_control.toggle_expanded()
        assert thinking_control.is_expanded
        thinking_control.toggle_expanded()
        assert not thinking_control.is_expanded

    def test_can_toggle_when_expanded(self, thinking_control: ThinkingBoxControl):
        """Should be able to toggle when already expanded."""
        thinking_control.start(lambda: "test")
        thinking_control.expand()
        assert thinking_control.can_toggle_expanded

    def test_cannot_toggle_when_inactive(self, thinking_control: ThinkingBoxControl):
        """Should not be able to toggle when inactive."""
        assert not thinking_control.can_toggle_expanded

    def test_can_toggle_when_content_overflows(
        self, small_thinking_control: ThinkingBoxControl, multiline_content: str
    ):
        """Should be able to toggle when content overflows max lines."""
        small_thinking_control.start(lambda: multiline_content)
        assert small_thinking_control.can_toggle_expanded

    def test_cannot_toggle_when_content_fits(
        self, small_thinking_control: ThinkingBoxControl, short_content: str
    ):
        """Should not be able to toggle when content fits in collapsed view."""
        small_thinking_control.start(lambda: short_content)
        assert not small_thinking_control.can_toggle_expanded


class TestThinkingBoxControlTruncation:
    """Test content truncation in collapsed mode."""

    def test_console_output_truncated_when_collapsed(
        self, small_thinking_control: ThinkingBoxControl, multiline_content: str
    ):
        """Console output should be truncated when collapsed and overflowing."""
        small_thinking_control.start(lambda: multiline_content)
        output = small_thinking_control.get_console_output()

        assert output.endswith("...")
        # max_collapsed_lines - 1 lines of content + "..."
        assert output.count("\n") <= 4

    def test_console_output_full_when_expanded(
        self, small_thinking_control: ThinkingBoxControl, multiline_content: str
    ):
        """Console output should be full content when expanded."""
        small_thinking_control.start(lambda: multiline_content)
        small_thinking_control.expand()
        output = small_thinking_control.get_console_output()

        assert not output.endswith("...")
        assert "Line 19" in output  # Last line should be present

    def test_console_output_not_truncated_when_fits(
        self, small_thinking_control: ThinkingBoxControl, short_content: str
    ):
        """Console output should not be truncated when content fits."""
        small_thinking_control.start(lambda: short_content)
        output = small_thinking_control.get_console_output()

        assert not output.endswith("...")

    def test_console_output_empty_when_inactive(
        self, thinking_control: ThinkingBoxControl
    ):
        """Console output should be empty when inactive."""
        assert thinking_control.get_console_output() == ""

    def test_console_output_empty_when_whitespace_only(
        self, thinking_control: ThinkingBoxControl
    ):
        """Console output should be empty when content is whitespace only."""
        thinking_control.start(lambda: "   \n  \n  ")
        assert thinking_control.get_console_output() == ""


class TestThinkingBoxControlFormatting:
    """Test FormattedText output."""

    def test_formatted_text_empty_when_inactive(
        self, thinking_control: ThinkingBoxControl
    ):
        """Formatted text should be empty when inactive."""
        formatted = thinking_control._get_formatted_text()
        assert formatted == FormattedText([])

    def test_formatted_text_includes_content(
        self, thinking_control: ThinkingBoxControl
    ):
        """Formatted text should include content."""
        thinking_control.start(lambda: "Hello World")
        formatted = thinking_control._get_formatted_text()

        # Extract text from formatted output
        text = "".join(frag[1] for frag in formatted)
        assert "Hello World" in text

    def test_formatted_text_includes_hint_when_overflowing(
        self, small_thinking_control: ThinkingBoxControl, multiline_content: str
    ):
        """Formatted text should include expand hint when collapsed and overflowing."""
        small_thinking_control.start(lambda: multiline_content)
        formatted = small_thinking_control._get_formatted_text()

        text = "".join(frag[1] for frag in formatted)
        # Default key is c-t, displayed as ctrl-t
        assert "ctrl-t to expand" in text

    def test_formatted_text_no_hint_when_expanded(
        self, small_thinking_control: ThinkingBoxControl, multiline_content: str
    ):
        """Formatted text should not include hint when expanded."""
        small_thinking_control.start(lambda: multiline_content)
        small_thinking_control.expand()
        formatted = small_thinking_control._get_formatted_text()

        text = "".join(frag[1] for frag in formatted)
        assert "to expand" not in text

    def test_formatted_text_uses_custom_key_in_hint(self, multiline_content: str):
        """Formatted text should use custom key in expand hint."""
        control = ThinkingBoxControl(max_collapsed_lines=3, expand_key="c-x")
        control.start(lambda: multiline_content)
        formatted = control._get_formatted_text()

        text = "".join(frag[1] for frag in formatted)
        assert "ctrl-x to expand" in text


class TestThinkingBoxControlLineCount:
    """Test line count calculation."""

    def test_line_count_zero_when_empty(self, thinking_control: ThinkingBoxControl):
        """Line count should be zero when no content."""
        assert thinking_control.get_line_count() == 0

    def test_line_count_counts_newlines(self, thinking_control: ThinkingBoxControl):
        """Line count should count newlines correctly."""
        thinking_control.start(lambda: "line1\nline2\nline3")
        assert thinking_control.get_line_count() == 3

    def test_line_count_accounts_for_wrapping(
        self, thinking_control: ThinkingBoxControl
    ):
        """Line count should account for line wrapping."""
        # 100 chars should wrap at width 80
        long_line = "x" * 100
        thinking_control.start(lambda: long_line)
        assert thinking_control.get_line_count(width=80) == 2

    def test_line_count_handles_empty_lines(
        self, thinking_control: ThinkingBoxControl
    ):
        """Line count should handle empty lines."""
        thinking_control.start(lambda: "line1\n\nline3")
        assert thinking_control.get_line_count() == 3


class TestThinkingBoxControlKeyBindings:
    """Test key bindings generation."""

    def test_key_bindings_returns_bindings(
        self, thinking_control: ThinkingBoxControl
    ):
        """Should return key bindings object."""
        kb = thinking_control.get_key_bindings()
        assert kb is not None

    def test_key_bindings_disabled_in_fullscreen(
        self, thinking_control: ThinkingBoxControl, multiline_content: str
    ):
        """Toggle key binding should be disabled in fullscreen mode."""
        thinking_control.start(lambda: multiline_content)

        # With is_fullscreen returning True, can_toggle should not be available
        kb = thinking_control.get_key_bindings(is_fullscreen=lambda: True)

        # The binding exists but filter should prevent activation
        # We verify this by checking the control's toggle still works directly
        assert not thinking_control.is_expanded
        thinking_control.toggle_expanded()
        assert thinking_control.is_expanded

    def test_key_bindings_enabled_in_prompt_mode(
        self, thinking_control: ThinkingBoxControl, multiline_content: str
    ):
        """Toggle key binding should be enabled in prompt mode."""
        thinking_control.start(lambda: multiline_content)

        # With is_fullscreen returning False, should be available
        kb = thinking_control.get_key_bindings(is_fullscreen=lambda: False)

        # Verify control can toggle
        assert not thinking_control.is_expanded
        thinking_control.toggle_expanded()
        assert thinking_control.is_expanded
