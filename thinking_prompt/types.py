"""
Type definitions for thinking_prompt: the type aliases and literals the
package's signatures use.
"""
from __future__ import annotations

from collections.abc import Coroutine
from typing import (
    Any,
    Callable,
    Literal,
    Union,
)

# =============================================================================
# Type Aliases
# =============================================================================

# Content format for thinking box rendering
ContentFormat = Literal["plain", "ansi"]

# Which end of overflowing thinking-box content stays visible: "tail" keeps
# the newest lines (streaming), "head" the first lines (e.g. a task list).
Overflow = Literal["tail", "head"]

# How a dialog is drawn: "box" floats a framed dialog over the session;
# "inline" draws it as rows between the prompt and the status bar.
Placement = Literal["box", "inline"]


InputWhileBusy = Literal["refuse", "queue"]


def check_choice(name: str, value: object, choices: tuple[str, ...]) -> None:
    """Raise ValueError unless ``value`` is one of ``choices``."""
    if value not in choices:
        listed = " or ".join(repr(choice) for choice in choices)
        raise ValueError(f"{name} must be {listed}, got {value!r}")


def check_count(name: str, value: object, least: int, *, optional: bool = False) -> None:
    """Raise ValueError unless ``value`` is an int (not a bool) of at least
    ``least``, or None when ``optional``. Checked where it's passed, so a
    bad count isn't first met while drawing."""
    if optional and value is None:
        return
    none = " (or None)" if optional else ""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an int{none}, got {value!r}")
    if value < least:
        raise ValueError(f"{name} must be at least {least}{none}, got {value!r}")


def check_input_while_busy(value: object) -> None:
    """Raise ValueError unless ``value`` is 'refuse' or 'queue'."""
    check_choice("input_while_busy", value, ("refuse", "queue"))


def check_placement(value: object, *, optional: bool = False) -> None:
    """Raise ValueError unless ``value`` is a Placement (or None, when ``optional``)."""
    if optional and value is None:
        return
    check_choice("placement", value, ("box", "inline"))

# Returns a thinking box's current content; the box re-reads it while drawn.
ContentCallback = Callable[[], str]

# Handles one line of submitted input: a function, or an async function
# (the session runs its coroutine as a task that Ctrl+C can cancel).
InputHandler = Union[
    Callable[[str], None], Callable[[str], Coroutine[Any, Any, None]]
]
