"""
Tests for the text helpers and removed types.
"""
from __future__ import annotations


class TestTruncateToLines:
    """A trailing newline is not a line of its own when truncating."""

    def test_trailing_newline_does_not_trigger_truncation(self):
        from thinking_prompt._text import truncate_to_lines

        assert truncate_to_lines("a\nb\nc\nd\n", 4) == "a\nb\nc\nd"

    def test_truncates_beyond_limit(self):
        from thinking_prompt._text import truncate_to_lines

        assert truncate_to_lines("a\nb\nc\nd\ne\n", 4) == "a\nb\nc\nd\n..."

    def test_ansi_trailing_newline_does_not_trigger_truncation(self):
        from thinking_prompt._text import truncate_ansi_to_lines

        assert truncate_ansi_to_lines("\033[1ma\033[0m\nb\n", 2) == "\033[1ma\033[0m\nb"


class TestTruncateTail:
    """overflow="tail" keeps the last lines, marker on top."""

    def test_plain_tail(self):
        from thinking_prompt._text import truncate_to_lines

        assert truncate_to_lines("a\nb\nc\nd\n", 2, overflow="tail") == "...\nc\nd"

    def test_plain_tail_that_fits_is_untouched(self):
        from thinking_prompt._text import truncate_to_lines

        assert truncate_to_lines("a\nb\n", 2, overflow="tail") == "a\nb"

    def test_ansi_tail_replays_style_state_at_the_cut(self):
        """A color opened in the cut-off part still applies to the kept
        lines: the skipped part's SGR codes are replayed after the marker."""
        from prompt_toolkit.formatted_text import (
            ANSI,
            fragment_list_to_text,
            to_formatted_text,
        )

        from thinking_prompt._text import truncate_ansi_to_lines

        out = truncate_ansi_to_lines("\x1b[31ma\nb\nc\x1b[0m\n", 1, overflow="tail")
        frags = list(to_formatted_text(ANSI(out)))  # ~one fragment per char
        assert fragment_list_to_text(frags) == "...\nc"
        assert all("ansired" not in s for s, t in frags if t == ".")
        assert all("ansired" in s for s, t in frags if t == "c")


class TestFormatExceptionDetail:
    """format_exception_detail(): one formatter for exception detail lines."""

    def test_exception_with_message_includes_type_and_message(self):
        from thinking_prompt._text import format_exception_detail

        assert format_exception_detail(KeyError("x")) == "KeyError: 'x'"

    def test_exception_without_message_is_just_the_type_name(self):
        from thinking_prompt._text import format_exception_detail

        assert format_exception_detail(RuntimeError()) == "RuntimeError"


class TestRemovedTypes:
    def test_message_role_is_gone(self):
        """A chat-role literal nothing used: not this UI library's concern."""
        import thinking_prompt
        import thinking_prompt.types as types_module

        assert not hasattr(thinking_prompt, "MessageRole")
        assert "MessageRole" not in thinking_prompt.__all__
        assert not hasattr(types_module, "MessageRole")
