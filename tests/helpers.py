"""Builders shared by the thinking-box tests."""
from __future__ import annotations

from typing import Any

from prompt_toolkit.formatted_text import (
    AnyFormattedText,
    fragment_list_to_text,
    to_formatted_text,
)
from prompt_toolkit.styles import Style

from thinking_prompt.display import Display
from thinking_prompt.manager import ThinkingBoxManager


def keep_console(display: Display) -> Display:
    """Make ``display`` keep what it would print to the console, in
    ``display.kept`` (one item per print, as it would print it), instead
    of printing it. History works as usual."""
    kept: list[AnyFormattedText] = []
    display._print_to_console = kept.append  # type: ignore[method-assign]
    display.kept = kept  # type: ignore[attr-defined]
    return display


def make_display() -> Display:
    """A Display that keeps its console output instead of printing it:
    echoed() reads it."""
    return keep_console(Display(get_style=lambda: Style([])))


def make_manager(display: Display | None = None, **kwargs: Any) -> ThinkingBoxManager:
    """A ThinkingBoxManager echoing to ``display`` (a new one by default)."""
    return ThinkingBoxManager(display if display is not None else make_display(), **kwargs)


def echoed(display: Display) -> list[str]:
    """What the display printed to the console, one string per print."""
    return [fragment_list_to_text(to_formatted_text(item)) for item in display.kept]


def transcript_texts(display: Display) -> list[str]:
    """The text of each transcript entry."""
    return [entry.text for entry in display.transcript.iter_entries()]
