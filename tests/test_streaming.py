"""
Tests for StreamingContent.
"""
from __future__ import annotations

import random

import pytest
from prompt_toolkit.formatted_text import ANSI, fragment_list_to_text, to_formatted_text

from thinking_prompt import StreamingContent


def _plain(text: str) -> str:
    """``text`` without its ANSI escapes."""
    return fragment_list_to_text(to_formatted_text(ANSI(text)))


class TestStreamingContentBasics:
    """Test basic functionality of StreamingContent."""

    def test_text_property(self):
        """text property should be alias for get_content()."""
        content = StreamingContent()
        content.append("Test")
        assert content.text == content.get_content()
        assert content.text == "Test"

    def test_clear_removes_all(self):
        """Clear should remove all content."""
        content = StreamingContent()
        content.append("One")
        content.append("Two")
        content.clear()
        assert content.get_content() == ""
        assert len(content) == 0


class TestStreamingContentSetLine:
    """Test set_line() method of StreamingContent."""

    def test_set_line_positive_index(self):
        """Set a specific line by positive index."""
        content = StreamingContent()
        content.append("line0\nline1\nline2\n")
        content.set_line(1, "REPLACED")
        assert content.text == "line0\nREPLACED\nline2\n"

    def test_set_line_negative_index(self):
        """Negative index -1 should target the last line, as len() counts it."""
        content = StreamingContent()
        content.append("line0\nline1\nline2\n")
        content.set_line(-1, "LAST")
        assert content.text == "line0\nline1\nLAST\n"

    def test_set_line_negative_index_minus_two(self):
        """Negative index -2 should target the second-to-last line."""
        content = StreamingContent()
        content.append("a\nb\nc\n")
        content.set_line(-2, "B")
        assert content.text == "a\nB\nc\n"

    def test_set_line_extends_with_empty_lines(self):
        """Index beyond current count extends with empty lines."""
        content = StreamingContent()
        content.append("line0\n")
        content.set_line(3, "line3")
        assert content.text == "line0\n\n\nline3\n"

    def test_set_line_negative_index_out_of_range_raises(self):
        """A negative index beyond the first line raises a clear IndexError
        naming the index the caller passed (not the normalized one)."""
        content = StreamingContent()
        content.append("only line\n")
        with pytest.raises(IndexError, match=r"line index -5 out of range"):
            content.set_line(-5, "nope")
        # Content untouched after the failed call.
        assert content.text == "only line\n"

    def test_set_line_no_trailing_newline(self):
        """Content without trailing newline should stay that way."""
        content = StreamingContent()
        content.append("hello\nworld")
        content.set_line(0, "HELLO")
        assert content.text == "HELLO\nworld"
        assert not content.text.endswith("\n")

    def test_set_line_single_line_with_newline(self):
        """Single line with trailing newline."""
        content = StreamingContent()
        content.append("only\n")
        content.set_line(0, "ONLY")
        assert content.text == "ONLY\n"

    def test_set_line_single_line_without_newline(self):
        """Single line without trailing newline."""
        content = StreamingContent()
        content.append("only")
        content.set_line(0, "ONLY")
        assert content.text == "ONLY"

    def test_set_line_rejects_text_of_more_than_one_line(self):
        """A newline in the text would add lines, shifting every index after it."""
        content = StreamingContent()
        content.append("a\nb\n")
        for text in ("x\ny", "x\n"):
            with pytest.raises(ValueError, match="one line"):
                content.set_line(0, text)
        assert content.text == "a\nb\n"

    def test_set_line_first_line_index_zero(self):
        """Index 0 should set the first line."""
        content = StreamingContent()
        content.append("first\nsecond\n")
        content.set_line(0, "FIRST")
        assert content.text == "FIRST\nsecond\n"

    def test_set_line_on_empty_content_starts_the_first_line(self):
        content = StreamingContent()
        content.set_line(0, "x")
        assert content.text == "x"

    def test_set_line_past_the_end_of_empty_content_pads(self):
        content = StreamingContent()
        content.set_line(2, "x")
        assert content.text == "\n\nx"

    def test_a_negative_index_on_empty_content_raises(self):
        """Empty content has no lines, so there is no last line to replace."""
        content = StreamingContent()
        with pytest.raises(IndexError, match=r"line index -1 out of range for 0 line\(s\)"):
            content.set_line(-1, "x")
        assert content.text == ""

    def test_a_negative_index_after_clear_raises(self):
        content = StreamingContent()
        content.append("a\n")
        content.clear()
        with pytest.raises(IndexError):
            content.set_line(-1, "x")


class TestLen:
    """len() counts lines; a trailing newline ends a line, it doesn't start one."""

    @pytest.mark.parametrize(
        "text, lines",
        [
            ("", 0),
            ("a", 1),
            ("a\n", 1),
            ("a\nb", 2),
            ("a\nb\n", 2),
            ("\n", 1),
            ("\n\n", 2),
            ("a\n\n", 2),
        ],
    )
    def test_counts_lines(self, text, lines):
        content = StreamingContent()
        content.append(text)
        assert len(content) == lines

    def test_counts_lines_across_appends(self):
        content = StreamingContent()
        for chunk in ("Hel", "lo\nWo", "rld", "\n", "!"):
            content.append(chunk)
        assert content.text == "Hello\nWorld\n!"
        assert len(content) == 3

    @pytest.mark.parametrize("text", ["a", "a\n", "a\nb", "a\nb\n", "\n", "a\n\n"])
    def test_the_last_counted_line_is_the_one_minus_one_replaces(self, text):
        by_len, by_minus_one = StreamingContent(), StreamingContent()
        by_len.append(text)
        by_minus_one.append(text)
        by_len.set_line(len(by_len) - 1, "LAST")
        by_minus_one.set_line(-1, "LAST")
        assert by_len.text == by_minus_one.text
        assert len(by_len) == len(text.splitlines())


class _ChunkReference:
    """The chunk-based StreamingContent that line storage replaced, with the
    one intended change: empty text has no lines (it used to have one empty
    line), so a negative index on it raises."""

    def __init__(self) -> None:
        self.text = ""

    def append(self, chunk: str) -> None:
        self.text += chunk

    def clear(self) -> None:
        self.text = ""

    def _lines(self) -> tuple[list[str], bool]:
        if not self.text:
            return [], False
        trailing_newline = self.text.endswith("\n")
        lines = self.text.split("\n")
        if trailing_newline:
            lines.pop()
        return lines, trailing_newline

    def __len__(self) -> int:
        return len(self._lines()[0])

    def set_line(self, index: int, text: str) -> None:
        lines, trailing_newline = self._lines()
        if index < 0:
            index += len(lines)
            if index < 0:
                raise IndexError(index)
        lines.extend([""] * (index + 1 - len(lines)))
        lines[index] = text
        self.text = "\n".join(lines) + ("\n" if trailing_newline else "")


class TestMatchesChunkStorage:
    """Storing lines changes no text: random writes give what chunks gave."""

    CHUNKS = ["", "a", "bc", "\n", "\n\n", "d\n", "e\nf", "\ng"]
    TEXTS = ["", "x", "yz"]

    def test_random_writes(self):
        for seed in range(200):
            rng = random.Random(seed)
            content, reference = StreamingContent(), _ChunkReference()
            ops: list[tuple] = []
            for _ in range(40):
                roll = rng.random()
                if roll < 0.5:
                    chunk = rng.choice(self.CHUNKS)
                    ops.append(("append", chunk))
                    content.append(chunk)
                    reference.append(chunk)
                elif roll < 0.95:
                    index, text = rng.randint(-4, 5), rng.choice(self.TEXTS)
                    ops.append(("set_line", index, text))
                    try:
                        reference.set_line(index, text)
                    except IndexError:
                        with pytest.raises(IndexError):
                            content.set_line(index, text)
                    else:
                        content.set_line(index, text)
                else:
                    ops.append(("clear",))
                    content.clear()
                    reference.clear()
                assert content.text == reference.text, f"seed {seed}: {ops}"
                assert len(content) == len(reference), f"seed {seed}: {ops}"


class TestStreamingContentRichMethods:
    """Test append_rich() and set_line_rich() on StreamingContent."""

    def test_append_rich_markup_string(self):
        """append_rich should convert Rich markup to ANSI."""
        pytest.importorskip("rich")
        content = StreamingContent()
        content.append_rich("[green]✓ Done[/green]\n")
        text = content.get_content()
        # Should contain ANSI escape codes and the text
        assert "✓ Done" in text
        assert "\033[" in text  # ANSI escape codes present

    def test_append_rich_text_object(self):
        """append_rich should handle Rich Text objects."""
        pytest.importorskip("rich")
        from rich.text import Text
        content = StreamingContent()
        content.append_rich(Text("Hello", style="bold"))
        text = content.get_content()
        assert "Hello" in text

    def test_append_rich_plain_string(self):
        """append_rich with plain string should produce output."""
        content = StreamingContent()
        content.append_rich("plain text\n")
        text = content.get_content()
        assert "plain text" in text

    def test_append_rich_keeps_the_newline_that_ends_a_line(self):
        """A task list built with append_rich, then updated line by line
        (the README's example): each append is its own line."""
        pytest.importorskip("rich")
        content = StreamingContent()
        for task in ("Download", "Process", "Report"):
            content.append_rich(f"[dim]  ○ {task}[/dim]\n")
        assert len(content) == 3
        content.set_line_rich(0, "[green]  ✓ Download[/green]")
        assert _plain(content.text) == "  ✓ Download\n  ○ Process\n  ○ Report\n"

    def test_append_rich_keeps_a_trailing_space(self):
        """Streamed words keep the space between them."""
        pytest.importorskip("rich")
        content = StreamingContent()
        content.append_rich("[bold]Hello[/bold] ")
        content.append_rich("world")
        assert _plain(content.text) == "Hello world"

    def test_set_line_rich_takes_markup_ending_its_line(self):
        """The newline that ends the line isn't a second line."""
        pytest.importorskip("rich")
        content = StreamingContent()
        content.append("line0\nline1\n")
        content.set_line_rich(0, "[green]done[/green]\n")
        assert _plain(content.text) == "done\nline1\n"

    def test_set_line_rich_markup(self):
        """set_line_rich should replace a line with Rich-converted content."""
        pytest.importorskip("rich")
        content = StreamingContent()
        content.append("line0\nline1\n")
        content.set_line_rich(0, "[green]✓ line0[/green]")
        text = content.get_content()
        assert "✓ line0" in text
        assert "\033[" in text  # ANSI escape codes

    def test_set_line_rich_rejects_markup_of_more_than_one_line(self):
        """Its lines after the first used to be dropped without a word."""
        content = StreamingContent()
        content.append("line0\nline1\n")
        with pytest.raises(ValueError, match="one line"):
            content.set_line_rich(0, "[green]first[/green]\nsecond")
        assert content.text == "line0\nline1\n"

    def test_set_line_rich_rejects_a_renderable_of_more_than_one_line(self):
        pytest.importorskip("rich")
        from rich.panel import Panel
        content = StreamingContent()
        content.append("line0\n")
        with pytest.raises(ValueError, match="one line"):
            content.set_line_rich(0, Panel("boxed"))
        assert content.text == "line0\n"

    def test_set_line_rich_keeps_the_other_lines(self):
        """set_line_rich replaces one line and leaves the rest."""
        content = StreamingContent()
        content.append("line0\nline1\n")
        content.set_line_rich(0, "[green]first[/green]")
        lines = content.get_content().split('\n')
        # line0 should be replaced, line1 preserved
        assert "first" in lines[0]
        assert "line1" in lines[1]

    def test_set_line_rich_negative_index(self):
        """set_line_rich should support negative indices."""
        content = StreamingContent()
        content.append("line0\nline1\n")
        content.set_line_rich(-1, "[bold]LAST[/bold]")
        text = content.get_content()
        assert "LAST" in text


class TestClose:
    """_close(): a thinking box closes its content when it finishes."""

    def test_close_returns_the_final_text(self):
        content = StreamingContent()
        content.append("a\n")
        assert content._close() == "a\n"

    def test_writes_after_close_change_nothing(self):
        changes: list[int] = []
        content = StreamingContent(on_change=lambda: changes.append(1))
        content.append("a\nb\n")
        changes.clear()

        content._close()
        content.append("late\n")
        content.set_line(0, "late")
        content.clear()
        content.append_rich("late")
        content.set_line_rich(0, "late")

        assert content.get_content() == "a\nb\n"
        assert changes == []
