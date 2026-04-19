"""
Formatted text history for ThinkingPromptSession.

Provides storage for styled text fragments to mimic console output in fullscreen mode.
"""
from __future__ import annotations

import threading
from collections.abc import Iterable
from typing import Callable

from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.formatted_text.base import OneStyleAndTextTuple


class FormattedTextHistory:
    """
    Thread-safe history of formatted text fragments.

    Stores styled text to mimic console output in fullscreen mode.
    This is a low-level abstraction that stores (style, text) pairs directly,
    without any chat-specific semantics.

    Example:
        history = FormattedTextHistory()

        # Add styled text
        history.append("class:user", ">>> hello\\n")
        history.append("class:response", "Hi there!\\n")

        # Get as FormattedText for display
        formatted = history.get_formatted_text()
    """

    def __init__(self) -> None:
        self._fragments: list[OneStyleAndTextTuple] = []
        self._lock = threading.RLock()
        self._on_change: Callable[[], None] | None = None

    def set_on_change(self, callback: Callable[[], None]) -> None:
        """Set callback to trigger when history changes."""
        self._on_change = callback

    def _notify_change(self) -> None:
        """Notify that history has changed."""
        if self._on_change:
            self._on_change()

    def append(self, style: str, text: str) -> None:
        """
        Append a styled text fragment.

        Args:
            style: Style class (e.g., "class:history.user-message").
            text: Text content.
        """
        with self._lock:
            self._fragments.append((style, text))
            self._notify_change()

    def append_formatted(
        self, formatted: Iterable[OneStyleAndTextTuple]
    ) -> None:
        """
        Append multiple fragments from a FormattedText or list.

        Args:
            formatted: FormattedText object or iterable of (style, text[, handler]) tuples.
        """
        with self._lock:
            self._fragments.extend(formatted)
            self._notify_change()

    def get_formatted_text(self) -> FormattedText:
        """
        Get all fragments as FormattedText.

        Returns:
            FormattedText containing all stored fragments.
        """
        with self._lock:
            return FormattedText(list(self._fragments))

    def clear(self) -> None:
        """Clear all fragments."""
        with self._lock:
            self._fragments.clear()
            self._notify_change()

    @property
    def is_empty(self) -> bool:
        """Check if history is empty."""
        with self._lock:
            return len(self._fragments) == 0

    def __len__(self) -> int:
        """Get number of fragments."""
        with self._lock:
            return len(self._fragments)
