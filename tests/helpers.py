"""Builders shared by the thinking-box tests."""
from __future__ import annotations

from typing import Any

from prompt_toolkit.formatted_text import fragment_list_to_text, to_formatted_text
from prompt_toolkit.styles import Style

from thinking_prompt.display import Display
from thinking_prompt.manager import ThinkingBoxManager


def make_display() -> Display:
    """A Display that keeps its console output instead of printing it.

    In full screen a Display caches what it would print; echoed() reads it.
    History works as in prompt mode.
    """
    return Display(get_style=lambda: Style([]), is_fullscreen=lambda: True)


def make_manager(display: Display | None = None, **kwargs: Any) -> ThinkingBoxManager:
    """A ThinkingBoxManager echoing to ``display`` (a new one by default)."""
    return ThinkingBoxManager(display if display is not None else make_display(), **kwargs)


def echoed(display: Display) -> list[str]:
    """What the display printed to the console, one string per print."""
    return [fragment_list_to_text(to_formatted_text(item)) for item in display._pending_output]


def history_texts(display: Display) -> list[str]:
    """The text of each history entry."""
    return [entry.text for entry in display.history.iter_entries()]
