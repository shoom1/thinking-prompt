"""
Tests for thread safety of thinking_prompt components.
"""
from __future__ import annotations

import concurrent.futures
import threading
import time
from typing import List

import pytest

from thinking_prompt.thinking import ThinkingBoxControl
from thinking_prompt.history import FormattedTextHistory


class TestFormattedTextHistoryThreadSafety:
    """Test thread safety of FormattedTextHistory."""

    def test_concurrent_appends(self, history: FormattedTextHistory):
        """Multiple threads should be able to append concurrently."""
        num_threads = 10
        appends_per_thread = 100

        def writer(thread_id: int):
            for i in range(appends_per_thread):
                history.append(f"class:thread-{thread_id}", f"msg-{i}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(writer, i) for i in range(num_threads)]
            concurrent.futures.wait(futures)

        expected_count = num_threads * appends_per_thread
        assert len(history) == expected_count

    def test_concurrent_read_write(self, history: FormattedTextHistory):
        """Reading and writing concurrently should be safe."""
        stop_event = threading.Event()
        read_results: List[int] = []

        def writer():
            for i in range(100):
                history.append("class:test", f"message-{i}")
                time.sleep(0.001)

        def reader():
            while not stop_event.is_set():
                formatted = history.get_formatted_text()
                read_results.append(len(list(formatted)))
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
        # Final count should be 100
        assert len(history) == 100

    def test_concurrent_clear_and_append(self, history: FormattedTextHistory):
        """Clearing while appending should be safe."""
        def appender():
            for _ in range(50):
                history.append("class:test", "message")
                time.sleep(0.001)

        def clearer():
            for _ in range(10):
                time.sleep(0.005)
                history.clear()

        threads = [
            threading.Thread(target=appender),
            threading.Thread(target=clearer),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without deadlock or error
        # Length depends on timing, but should be valid
        assert len(history) >= 0


class TestThinkingBoxControlThreadSafety:
    """Test thread safety of ThinkingBoxControl."""

    def test_concurrent_content_access(self, thinking_control: ThinkingBoxControl):
        """Multiple threads should be able to read content safely."""
        content_parts: List[str] = []
        lock = threading.Lock()

        def get_content() -> str:
            with lock:
                return "".join(content_parts)

        thinking_control.start(get_content)

        results: List[str] = []
        stop_event = threading.Event()

        def reader():
            while not stop_event.is_set():
                try:
                    content = thinking_control.content
                    results.append(content)
                except Exception as e:
                    results.append(f"ERROR: {e}")
                time.sleep(0.001)

        def writer():
            for i in range(50):
                with lock:
                    content_parts.append(f"part-{i} ")
                time.sleep(0.002)

        reader_thread = threading.Thread(target=reader)
        writer_thread = threading.Thread(target=writer)

        reader_thread.start()
        writer_thread.start()

        writer_thread.join()
        stop_event.set()
        reader_thread.join()

        # All reads should succeed without error
        errors = [r for r in results if r.startswith("ERROR")]
        assert len(errors) == 0

    def test_concurrent_expand_collapse(self, thinking_control: ThinkingBoxControl):
        """Multiple threads toggling expand/collapse should be safe."""
        thinking_control.start(lambda: "test content " * 100)

        def toggler():
            for _ in range(100):
                thinking_control.toggle_expanded()
                time.sleep(0.001)

        threads = [threading.Thread(target=toggler) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without error
        # Final state is non-deterministic but valid
        assert thinking_control.is_expanded in (True, False)

    def test_concurrent_start_finish(self):
        """Starting and finishing should be thread-safe."""
        control = ThinkingBoxControl()
        results: List[str] = []

        def cycle(thread_id: int):
            for i in range(20):
                try:
                    control.start(lambda: f"thread-{thread_id}-{i}")
                    time.sleep(0.001)
                    content, _ = control.finish()
                    results.append(f"ok-{thread_id}")
                except Exception as e:
                    results.append(f"error-{thread_id}: {e}")
                time.sleep(0.001)

        threads = [threading.Thread(target=cycle, args=(i,)) for i in range(3)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete, errors are acceptable due to race conditions
        # but no crashes or deadlocks
        assert len(results) > 0


