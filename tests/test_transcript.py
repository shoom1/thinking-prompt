"""
Tests for Transcript.
"""
from __future__ import annotations

from prompt_toolkit.formatted_text import FormattedText

from thinking_prompt.transcript import Transcript


class TestTranscriptBasics:
    """Test basic functionality of Transcript."""

    def test_initial_state_empty(self, transcript: Transcript):
        """History should be empty when first created."""
        assert transcript.is_empty
        assert len(transcript) == 0

    def test_append_adds_an_entry(self, transcript: Transcript):
        """Append should add one styled entry."""
        transcript.append("class:test", "Hello")

        assert not transcript.is_empty
        assert len(transcript) == 1

    def test_each_append_is_an_entry(self, transcript: Transcript):
        """Each append should add an entry of its own."""
        transcript.append("class:a", "First")
        transcript.append("class:b", "Second")
        transcript.append("class:c", "Third")

        assert len(transcript) == 3

    def test_get_formatted_text_renders_every_entry(
        self, transcript: Transcript
    ):
        """get_formatted_text should render every entry."""
        transcript.append("class:a", "First")
        transcript.append("class:b", "Second")

        formatted = transcript.get_formatted_text()

        assert isinstance(formatted, FormattedText)
        assert len(list(formatted)) == 2

    def test_get_formatted_text_preserves_styles(
        self, transcript: Transcript
    ):
        """get_formatted_text should preserve style information."""
        transcript.append("class:user", "User text")
        transcript.append("class:assistant", "Assistant text")

        formatted = transcript.get_formatted_text()
        fragments = list(formatted)

        assert fragments[0] == ("class:user", "User text")
        assert fragments[1] == ("class:assistant", "Assistant text")

    def test_clear_removes_every_entry(self, transcript: Transcript):
        """Clear should remove every entry."""
        transcript.append("class:a", "First")
        transcript.append("class:b", "Second")
        transcript.clear()

        assert transcript.is_empty
        assert len(transcript) == 0


class TestTranscriptAppendFormatted:
    """Test append_formatted functionality."""

    def test_append_formatted_is_one_entry_with_its_fragments(
        self, transcript: Transcript
    ):
        """append_formatted should accept FormattedText (or a list of tuples)."""
        fragments = [
            ("class:a", "First"),
            ("class:b", "Second"),
        ]
        transcript.append_formatted(FormattedText(fragments))

        # __len__ counts entries, not fragments: one append_formatted call
        # is one entry even though it carries two fragments.
        assert len(transcript) == 1
        assert list(transcript.get_formatted_text()) == fragments

    def test_append_formatted_adds_to_existing_entries(self, transcript: Transcript):
        """append_formatted should add an entry after the existing ones."""
        transcript.append("class:existing", "Existing")
        transcript.append_formatted([("class:new", "New")])

        assert len(transcript) == 2


class TestTranscriptEdgeCases:
    """Test edge cases."""

    def test_empty_text_is_an_entry(self, transcript: Transcript):
        """Should keep an entry with empty text."""
        transcript.append("class:test", "")
        assert len(transcript) == 1

    def test_empty_style_is_kept(self, transcript: Transcript):
        """Should handle empty style."""
        transcript.append("", "Text without style")
        formatted = transcript.get_formatted_text()
        fragments = list(formatted)
        assert fragments[0] == ("", "Text without style")

    def test_unicode_content(self, transcript: Transcript):
        """Should handle unicode content."""
        transcript.append("class:test", "Hello 世界 🌍")
        formatted = transcript.get_formatted_text()
        fragments = list(formatted)
        assert fragments[0][1] == "Hello 世界 🌍"

    def test_multiline_content(self, transcript: Transcript):
        """Should handle multiline content."""
        transcript.append("class:test", "Line 1\nLine 2\nLine 3")
        formatted = transcript.get_formatted_text()
        fragments = list(formatted)
        assert "\n" in fragments[0][1]

    def test_get_formatted_text_returns_copy(self, transcript: Transcript):
        """get_formatted_text should return a copy, not the internal list."""
        transcript.append("class:test", "Original")
        formatted1 = transcript.get_formatted_text()

        transcript.append("class:test", "Added")
        formatted2 = transcript.get_formatted_text()

        # First formatted text should not be affected by later additions
        assert len(list(formatted1)) == 1
        assert len(list(formatted2)) == 2


class TestTypedEntries:
    def test_markdown_entry_renders_through_callback_and_caches(self):
        calls = []

        def render(src):
            calls.append(src)
            return f"\x1b[1m{src}\x1b[0m"

        h = Transcript(render_markdown=render)
        h.append_markdown("# Title")
        first = h.get_formatted_text()
        second = h.get_formatted_text()
        assert calls == ["# Title"]  # cached after first render
        assert "Title" in "".join(t for _, t in first)
        assert first == second

    def test_invalidate_rerenders_markdown_not_ansi(self):
        md_calls = []
        h = Transcript(render_markdown=lambda s: (md_calls.append(s) or s))
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
        h = Transcript(render_code=lambda src, lang: f"{lang}:{src}")
        h.append_code("x = 1", "python")
        text = "".join(t for _, t in h.get_formatted_text())
        assert "python:x = 1" in text

    def test_render_callback_none_falls_back_to_plain(self):
        h = Transcript()
        h.append_markdown("# raw")
        text = "".join(t for _, t in h.get_formatted_text())
        assert "# raw" in text

    def test_max_entries_trims_oldest(self):
        h = Transcript(max_entries=2)
        h.append("class:a", "one")
        h.append("class:a", "two")
        h.append("class:a", "three")
        text = "".join(t for _, t in h.get_formatted_text())
        assert "one" not in text and "two" in text and "three" in text
        assert len(h) == 2

    def test_styled_and_formatted_unchanged(self):
        h = Transcript()
        h.append("class:x", "hello\n")
        h.append_formatted([("bold", "world")])
        frags = list(h.get_formatted_text())
        assert ("class:x", "hello\n") in frags
        assert ("bold", "world") in frags
