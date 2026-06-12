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
        """Finishing should return content, expansion state, and format."""
        thinking_control.start(lambda: "test content")
        content, was_expanded, fmt = thinking_control.finish()

        assert content == "test content"
        assert not was_expanded
        assert fmt == "plain"

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
        content, was_expanded, fmt = thinking_control.finish()

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


class TestThinkingBoxControlAnsiFormat:
    """Test ANSI format rendering in ThinkingBoxControl."""

    def test_default_format_is_plain(self, thinking_control: ThinkingBoxControl):
        """Default content format should be plain."""
        assert thinking_control.content_format == "plain"

    def test_start_with_ansi_format(self, thinking_control: ThinkingBoxControl):
        """Starting with ansi format should set the format."""
        thinking_control.start(lambda: "test", content_format="ansi")
        assert thinking_control.content_format == "ansi"

    def test_set_content_format(self, thinking_control: ThinkingBoxControl):
        """set_content_format should change the format dynamically."""
        thinking_control.start(lambda: "test")
        assert thinking_control.content_format == "plain"
        thinking_control.set_content_format("ansi")
        assert thinking_control.content_format == "ansi"

    def test_finish_resets_format_to_plain(self, thinking_control: ThinkingBoxControl):
        """Finishing should reset content format to plain."""
        thinking_control.start(lambda: "test", content_format="ansi")
        _, _, fmt = thinking_control.finish()
        assert fmt == "ansi"
        assert thinking_control.content_format == "plain"

    def test_ansi_formatted_text_parses_escape_codes(self, thinking_control: ThinkingBoxControl):
        """ANSI format should parse escape codes in formatted text."""
        # \033[32m = green, \033[0m = reset
        ansi_content = "\033[32m✓ Step 1\033[0m\n"
        thinking_control.start(lambda: ansi_content, content_format="ansi")
        formatted = thinking_control._get_formatted_text()

        # Should have fragments (ANSI parsed into styled fragments)
        assert len(formatted) > 0
        text = "".join(frag[1] for frag in formatted)
        assert "✓ Step 1" in text

    def test_ansi_truncation_with_hint(self, small_thinking_control: ThinkingBoxControl):
        """ANSI content should be truncated with hint when overflowing."""
        lines = [f"\033[32mLine {i}\033[0m" for i in range(20)]
        content = "\n".join(lines)
        small_thinking_control.start(lambda: content, content_format="ansi")
        formatted = small_thinking_control._get_formatted_text()

        text = "".join(frag[1] for frag in formatted)
        assert "ctrl-t to expand" in text

    def test_ansi_no_truncation_when_expanded(self, small_thinking_control: ThinkingBoxControl):
        """ANSI content should show fully when expanded."""
        lines = [f"\033[32mLine {i}\033[0m" for i in range(20)]
        content = "\n".join(lines)
        small_thinking_control.start(lambda: content, content_format="ansi")
        small_thinking_control.expand()
        formatted = small_thinking_control._get_formatted_text()

        text = "".join(frag[1] for frag in formatted)
        assert "Line 19" in text
        assert "to expand" not in text

    def test_plain_format_unchanged(self, thinking_control: ThinkingBoxControl):
        """Plain format should work exactly as before."""
        thinking_control.start(lambda: "Hello World")
        formatted = thinking_control._get_formatted_text()
        assert len(formatted) == 1
        assert formatted[0] == ("class:thinking-box", "Hello World")
