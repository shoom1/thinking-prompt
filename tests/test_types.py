"""
Tests for the text helpers.
"""
from __future__ import annotations


class TestFormatExceptionDetail:
    """format_exception_detail(): one formatter for exception detail lines."""

    def test_exception_with_message_includes_type_and_message(self):
        from thinking_prompt._text import format_exception_detail

        assert format_exception_detail(KeyError("x")) == "KeyError: 'x'"

    def test_exception_without_message_is_just_the_type_name(self):
        from thinking_prompt._text import format_exception_detail

        assert format_exception_detail(RuntimeError()) == "RuntimeError"


class TestCoalesce:
    """Merging same-style fragments (the transcript's ANSI and a box's lines)."""

    def test_merges_adjacent_same_style(self):
        from thinking_prompt._text import coalesce

        frags = [("bold", "a"), ("bold", "b"), ("", "c"), ("", "d"), ("bold", "e")]
        assert coalesce(frags) == [("bold", "ab"), ("", "cd"), ("bold", "e")]

    def test_drops_empty_text(self):
        from thinking_prompt._text import coalesce

        assert coalesce([("x", ""), ("x", "a")]) == [("x", "a")]

    def test_preserves_handler_fragments_unmerged(self):
        """3-tuple (mouse-handler) fragments must survive coalescing intact:
        never merged into neighbors in either direction, handler preserved."""
        from thinking_prompt._text import coalesce

        handler = lambda e: None  # noqa: E731
        frags = [("x", "a"), ("x", "b", handler), ("x", "c"), ("x", "d")]
        result = coalesce(frags)
        assert result == [("x", "a"), ("x", "b", handler), ("x", "cd")]
        assert result[1][2] is handler

    def test_drops_empty_text_handler_fragments(self):
        from thinking_prompt._text import coalesce

        handler = lambda e: None  # noqa: E731
        assert coalesce([("x", "", handler), ("x", "a")]) == [("x", "a")]

    def test_a_long_run_is_joined_once(self):
        """A line a million characters long, in one style, as the ANSI
        parser makes it: adding to the run a fragment at a time copies it
        each time (seconds at this length), joining it once doesn't."""
        import time

        from thinking_prompt._text import coalesce

        started = time.perf_counter()
        result = coalesce([("x", "a")] * 1_000_000)
        assert time.perf_counter() - started < 2
        assert result == [("x", "a" * 1_000_000)]
