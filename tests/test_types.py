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
