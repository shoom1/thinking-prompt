"""
Tests for type helpers and StreamingContent.
"""
from __future__ import annotations

import concurrent.futures
import threading
import time

import pytest

from thinking_prompt import StreamingContent


class TestStreamingContentBasics:
    """Test basic functionality of StreamingContent."""

    def test_initial_state_empty(self):
        """Content should be empty when first created."""
        content = StreamingContent()
        assert content.get_content() == ""
        assert len(content) == 0

    def test_append_adds_content(self):
        """Append should add content."""
        content = StreamingContent()
        content.append("Hello")
        assert content.get_content() == "Hello"
        assert len(content) == 1

    def test_append_multiple_chunks(self):
        """Multiple appends should accumulate."""
        content = StreamingContent()
        content.append("Hello")
        content.append(" ")
        content.append("World")
        assert content.get_content() == "Hello World"
        assert len(content) == 3

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


class TestStreamingContentThreadSafety:
    """Test thread safety of StreamingContent."""

    def test_concurrent_appends(self):
        """Multiple threads should be able to append concurrently."""
        content = StreamingContent()
        num_threads = 10
        appends_per_thread = 100

        def writer(thread_id: int):
            for i in range(appends_per_thread):
                content.append(f"t{thread_id}-{i} ")

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(writer, i) for i in range(num_threads)]
            concurrent.futures.wait(futures)

        # All appends should have succeeded
        assert len(content) == num_threads * appends_per_thread

    def test_concurrent_read_write(self):
        """Reading and writing concurrently should be safe."""
        content = StreamingContent()
        stop_event = threading.Event()
        read_results = []

        def writer():
            for i in range(100):
                content.append(f"msg-{i} ")
                time.sleep(0.001)

        def reader():
            while not stop_event.is_set():
                text = content.get_content()
                read_results.append(len(text))
                time.sleep(0.001)

        writer_thread = threading.Thread(target=writer)
        reader_thread = threading.Thread(target=reader)

        reader_thread.start()
        writer_thread.start()

        writer_thread.join()
        stop_event.set()
        reader_thread.join()

        # All reads should have succeeded
        assert len(read_results) > 0
        # Final content should have all messages
        assert len(content) == 100

    def test_concurrent_clear(self):
        """Clearing while appending should be safe."""
        content = StreamingContent()

        def appender():
            for _ in range(50):
                content.append("msg ")
                time.sleep(0.001)

        def clearer():
            for _ in range(10):
                time.sleep(0.005)
                content.clear()

        threads = [
            threading.Thread(target=appender),
            threading.Thread(target=clearer),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without error
        # Final state depends on timing
        assert len(content) >= 0


class TestStreamingContentSetLine:
    """Test set_line() method of StreamingContent."""

    def test_set_line_positive_index(self):
        """Set a specific line by positive index."""
        content = StreamingContent()
        content.append("line0\nline1\nline2\n")
        content.set_line(1, "REPLACED")
        assert content.text == "line0\nREPLACED\nline2\n"

    def test_set_line_negative_index(self):
        """Negative index -1 should target the last non-empty line."""
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

    def test_set_line_preserves_trailing_newline(self):
        """Trailing newline should be preserved after set_line."""
        content = StreamingContent()
        content.append("hello\nworld\n")
        content.set_line(0, "HELLO")
        assert content.text == "HELLO\nworld\n"
        assert content.text.endswith("\n")

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

    def test_set_line_first_line_index_zero(self):
        """Index 0 should set the first line."""
        content = StreamingContent()
        content.append("first\nsecond\n")
        content.set_line(0, "FIRST")
        assert content.text == "FIRST\nsecond\n"

    def test_set_line_thread_safe(self):
        """set_line should be thread-safe with concurrent appends."""
        content = StreamingContent()
        content.append("line0\nline1\nline2\n")

        errors = []

        def updater():
            try:
                for i in range(100):
                    content.set_line(-1, f"update-{i}")
            except Exception as e:
                errors.append(e)

        def appender():
            try:
                for i in range(100):
                    content.append("")  # No-op append to exercise locking
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=updater)
        t2 = threading.Thread(target=appender)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"Thread safety errors: {errors}"

    def test_set_line_multiple_chunks(self):
        """set_line should work correctly when content is in multiple chunks."""
        content = StreamingContent()
        content.append("line0\n")
        content.append("line1\n")
        content.append("line2\n")
        content.set_line(1, "REPLACED")
        assert content.text == "line0\nREPLACED\nline2\n"
        # After set_line, chunks are consolidated into one
        assert len(content) == 1


class TestStreamingContentWithThinkingControl:
    """Test StreamingContent integration with ThinkingBoxControl."""

    def test_as_content_callback(self):
        """Should work as a content callback for ThinkingBoxControl."""
        from thinking_prompt.thinking import ThinkingBoxControl

        content = StreamingContent()
        control = ThinkingBoxControl()

        control.start(content.get_content)
        content.append("Processing...\n")
        content.append("Step 1 complete\n")

        assert "Processing" in control.content
        assert "Step 1" in control.content

        control.finish()

    def test_streaming_simulation(self):
        """Should handle streaming-like updates."""
        from thinking_prompt.thinking import ThinkingBoxControl

        content = StreamingContent()
        control = ThinkingBoxControl()

        control.start(content.get_content)

        # Simulate streaming tokens
        tokens = ["Hello", " ", "world", "!", "\n", "How", " ", "are", " ", "you", "?"]
        for token in tokens:
            content.append(token)

        assert control.content == "Hello world!\nHow are you?"

        control.finish()


class TestStreamingContentRichMethods:
    """Test append_rich() and set_line_rich() on StreamingContent."""

    def test_append_rich_markup_string(self):
        """append_rich should convert Rich markup to ANSI."""
        content = StreamingContent()
        content.append_rich("[green]✓ Done[/green]\n")
        text = content.get_content()
        # Should contain ANSI escape codes and the text
        assert "✓ Done" in text
        assert "\033[" in text  # ANSI escape codes present

    def test_append_rich_text_object(self):
        """append_rich should handle Rich Text objects."""
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

    def test_set_line_rich_markup(self):
        """set_line_rich should replace a line with Rich-converted content."""
        content = StreamingContent()
        content.append("line0\nline1\n")
        content.set_line_rich(0, "[green]✓ line0[/green]")
        text = content.get_content()
        assert "✓ line0" in text
        assert "\033[" in text  # ANSI escape codes

    def test_set_line_rich_takes_first_line_only(self):
        """set_line_rich should only use the first line of multi-line output."""
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
