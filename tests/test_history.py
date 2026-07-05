"""
Tests for FormattedTextHistory.
"""
from __future__ import annotations

from prompt_toolkit.formatted_text import FormattedText

from thinking_prompt.history import FormattedTextHistory, _coalesce


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

        # __len__ counts entries, not fragments: one append_formatted call
        # is one entry even though it carries two fragments.
        assert len(history) == 1

    def test_append_formatted_with_formatted_text(
        self, history: FormattedTextHistory
    ):
        """append_formatted should accept FormattedText object."""
        formatted = FormattedText([
            ("class:a", "First"),
            ("class:b", "Second"),
        ])
        history.append_formatted(formatted)

        # __len__ counts entries, not fragments: one append_formatted call
        # is one entry even though it carries two fragments.
        assert len(history) == 1

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


class TestCoalesce:
    def test_merges_adjacent_same_style(self):
        frags = [("bold", "a"), ("bold", "b"), ("", "c"), ("", "d"), ("bold", "e")]
        assert _coalesce(frags) == [("bold", "ab"), ("", "cd"), ("bold", "e")]

    def test_drops_empty_text(self):
        assert _coalesce([("x", ""), ("x", "a")]) == [("x", "a")]

    def test_preserves_handler_fragments_unmerged(self):
        """3-tuple (mouse-handler) fragments must survive coalescing intact:
        never merged into neighbors in either direction, handler preserved."""
        handler = lambda e: None  # noqa: E731
        frags = [("x", "a"), ("x", "b", handler), ("x", "c"), ("x", "d")]
        result = _coalesce(frags)
        assert result == [("x", "a"), ("x", "b", handler), ("x", "cd")]
        assert result[1][2] is handler

    def test_drops_empty_text_handler_fragments(self):
        handler = lambda e: None  # noqa: E731
        assert _coalesce([("x", "", handler), ("x", "a")]) == [("x", "a")]


class TestTypedEntries:
    def test_markdown_entry_renders_through_callback_and_caches(self):
        calls = []

        def render(src):
            calls.append(src)
            return f"\x1b[1m{src}\x1b[0m"

        h = FormattedTextHistory(render_markdown=render)
        h.append_markdown("# Title")
        first = h.get_formatted_text()
        second = h.get_formatted_text()
        assert calls == ["# Title"]  # cached after first render
        assert "Title" in "".join(t for _, t in first)
        assert first == second

    def test_invalidate_rerenders_markdown_not_ansi(self):
        md_calls = []
        h = FormattedTextHistory(render_markdown=lambda s: (md_calls.append(s) or s))
        h.append_markdown("hello")
        h.append_ansi("\x1b[31mred\x1b[0m")
        h.get_formatted_text()
        assert md_calls == ["hello"]
        h.invalidate_render_caches()
        h.get_formatted_text()
        assert md_calls == ["hello", "hello"]  # markdown re-rendered
        # ansi entry: baked — content still present and unchanged
        text = "".join(t for _, t in h.get_formatted_text())
        assert "red" in text

    def test_code_entry_renders_with_language(self):
        h = FormattedTextHistory(render_code=lambda src, lang: f"{lang}:{src}")
        h.append_code("x = 1", "python")
        text = "".join(t for _, t in h.get_formatted_text())
        assert "python:x = 1" in text

    def test_render_callback_none_falls_back_to_plain(self):
        h = FormattedTextHistory()
        h.append_markdown("# raw")
        text = "".join(t for _, t in h.get_formatted_text())
        assert "# raw" in text

    def test_max_entries_trims_oldest(self):
        h = FormattedTextHistory(max_entries=2)
        h.append("class:a", "one")
        h.append("class:a", "two")
        h.append("class:a", "three")
        text = "".join(t for _, t in h.get_formatted_text())
        assert "one" not in text and "two" in text and "three" in text
        assert len(h) == 2

    def test_styled_and_formatted_unchanged(self):
        h = FormattedTextHistory()
        h.append("class:x", "hello\n")
        h.append_formatted([("bold", "world")])
        frags = list(h.get_formatted_text())
        assert ("class:x", "hello\n") in frags
        assert ("bold", "world") in frags


class TestRevision:
    """revision must keep growing even once history_limit trimming makes
    len() saturate, or fullscreen auto-scroll (which used to key off
    len(history)) freezes forever once the cap is hit."""

    def test_revision_grows_on_append(self):
        h = FormattedTextHistory()
        assert h.revision == 0
        h.append("class:a", "one")
        r1 = h.revision
        assert r1 > 0
        h.append("class:a", "two")
        assert h.revision > r1

    def test_revision_keeps_growing_past_max_entries_trim(self):
        h = FormattedTextHistory(max_entries=2)
        revisions = []
        for i in range(4):
            h.append("class:a", f"entry-{i}")
            revisions.append(h.revision)

        # len() saturates at the cap...
        assert len(h) == 2
        # ...but revision must have strictly increased on every append,
        # never saturating like len() does.
        assert revisions == sorted(set(revisions))
        assert all(b > a for a, b in zip(revisions, revisions[1:]))

    def test_revision_grows_on_clear(self):
        h = FormattedTextHistory()
        h.append("class:a", "one")
        r1 = h.revision
        h.clear()
        assert h.revision > r1

    def test_revision_grows_on_invalidate_render_caches(self):
        h = FormattedTextHistory()
        h.append_markdown("# hi")
        r1 = h.revision
        h.invalidate_render_caches()
        assert h.revision > r1
