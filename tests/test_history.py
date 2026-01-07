"""
Tests for FormattedTextHistory.
"""
from __future__ import annotations

import pytest
from prompt_toolkit.formatted_text import FormattedText

from thinking_prompt.history import FormattedTextHistory


class TestFormattedTextHistoryBasics:
    """Test basic functionality of FormattedTextHistory."""

    def test_initial_state_empty(self, history: FormattedTextHistory):
        """History should be empty when first created."""
        assert history.is_empty
        assert len(history) == 0

    def test_append_adds_fragment(self, history: FormattedTextHistory):
        """Append should add a styled fragment."""
        history.append("class:test", "Hello")

        assert not history.is_empty
        assert len(history) == 1

    def test_append_multiple_fragments(self, history: FormattedTextHistory):
        """Multiple appends should accumulate fragments."""
        history.append("class:a", "First")
        history.append("class:b", "Second")
        history.append("class:c", "Third")

        assert len(history) == 3

    def test_get_formatted_text_returns_all_fragments(
        self, history: FormattedTextHistory
    ):
        """get_formatted_text should return all fragments."""
        history.append("class:a", "First")
        history.append("class:b", "Second")

        formatted = history.get_formatted_text()

        assert isinstance(formatted, FormattedText)
        assert len(list(formatted)) == 2

    def test_get_formatted_text_preserves_styles(
        self, history: FormattedTextHistory
    ):
        """get_formatted_text should preserve style information."""
        history.append("class:user", "User text")
        history.append("class:assistant", "Assistant text")

        formatted = history.get_formatted_text()
        fragments = list(formatted)

        assert fragments[0] == ("class:user", "User text")
        assert fragments[1] == ("class:assistant", "Assistant text")

    def test_clear_removes_all_fragments(self, history: FormattedTextHistory):
        """Clear should remove all fragments."""
        history.append("class:a", "First")
        history.append("class:b", "Second")
        history.clear()

        assert history.is_empty
        assert len(history) == 0


class TestFormattedTextHistoryAppendFormatted:
    """Test append_formatted functionality."""

    def test_append_formatted_with_list(self, history: FormattedTextHistory):
        """append_formatted should accept list of tuples."""
        fragments = [
            ("class:a", "First"),
            ("class:b", "Second"),
        ]
        history.append_formatted(fragments)

        assert len(history) == 2

    def test_append_formatted_with_formatted_text(
        self, history: FormattedTextHistory
    ):
        """append_formatted should accept FormattedText object."""
        formatted = FormattedText([
            ("class:a", "First"),
            ("class:b", "Second"),
        ])
        history.append_formatted(formatted)

        assert len(history) == 2

    def test_append_formatted_extends_existing(self, history: FormattedTextHistory):
        """append_formatted should extend existing fragments."""
        history.append("class:existing", "Existing")
        history.append_formatted([("class:new", "New")])

        assert len(history) == 2


class TestFormattedTextHistoryChangeNotification:
    """Test change notification callback."""

    def test_on_change_called_on_append(self, history: FormattedTextHistory):
        """on_change callback should be called when appending."""
        changes = []
        history.set_on_change(lambda: changes.append(True))

        history.append("class:test", "Test")

        assert len(changes) == 1

    def test_on_change_called_on_append_formatted(
        self, history: FormattedTextHistory
    ):
        """on_change callback should be called when append_formatted."""
        changes = []
        history.set_on_change(lambda: changes.append(True))

        history.append_formatted([("class:test", "Test")])

        assert len(changes) == 1

    def test_on_change_called_on_clear(self, history: FormattedTextHistory):
        """on_change callback should be called when clearing."""
        history.append("class:test", "Test")

        changes = []
        history.set_on_change(lambda: changes.append(True))
        history.clear()

        assert len(changes) == 1

    def test_on_change_not_called_if_not_set(self, history: FormattedTextHistory):
        """Should not error if no on_change callback is set."""
        # This should not raise
        history.append("class:test", "Test")
        history.clear()


class TestFormattedTextHistoryEdgeCases:
    """Test edge cases."""

    def test_empty_string_fragment(self, history: FormattedTextHistory):
        """Should handle empty string fragments."""
        history.append("class:test", "")
        assert len(history) == 1

    def test_empty_style_fragment(self, history: FormattedTextHistory):
        """Should handle empty style."""
        history.append("", "Text without style")
        formatted = history.get_formatted_text()
        fragments = list(formatted)
        assert fragments[0] == ("", "Text without style")

    def test_unicode_content(self, history: FormattedTextHistory):
        """Should handle unicode content."""
        history.append("class:test", "Hello 世界 🌍")
        formatted = history.get_formatted_text()
        fragments = list(formatted)
        assert fragments[0][1] == "Hello 世界 🌍"

    def test_multiline_content(self, history: FormattedTextHistory):
        """Should handle multiline content."""
        history.append("class:test", "Line 1\nLine 2\nLine 3")
        formatted = history.get_formatted_text()
        fragments = list(formatted)
        assert "\n" in fragments[0][1]

    def test_get_formatted_text_returns_copy(self, history: FormattedTextHistory):
        """get_formatted_text should return a copy, not the internal list."""
        history.append("class:test", "Original")
        formatted1 = history.get_formatted_text()

        history.append("class:test", "Added")
        formatted2 = history.get_formatted_text()

        # First formatted text should not be affected by later additions
        assert len(list(formatted1)) == 1
        assert len(list(formatted2)) == 2
