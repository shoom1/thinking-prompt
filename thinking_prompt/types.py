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


def check_input_while_busy(value: object) -> None:
    """Raise ValueError unless ``value`` is 'refuse' or 'queue'."""
    if value not in ("refuse", "queue"):
        raise ValueError(f"input_while_busy must be 'refuse' or 'queue', got {value!r}")


def check_placement(value: object, *, optional: bool = False) -> None:
    """Raise ValueError unless ``value`` is a Placement (or None, when ``optional``)."""
    if optional and value is None:
        return
    if value not in ("box", "inline"):
        raise ValueError(f"placement must be 'box' or 'inline', got {value!r}")

# Returns a thinking box's current content; the box re-reads it while drawn.
ContentCallback = Callable[[], str]

# Handles one line of submitted input: a function, or an async function
# (the session runs its coroutine as a task that Ctrl+C can cancel).
InputHandler = Union[
    Callable[[str], None], Callable[[str], Coroutine[Any, Any, None]]
]
