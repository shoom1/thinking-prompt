"""
Text helpers shared by the thinking box, the console echo, the repaint and
error lines (internal).
"""
from __future__ import annotations

import re

from .types import Overflow

# SGR (color/style) escape sequences — the only escapes thinking content is
# expected to carry. Used to measure/replay styling without the text.
ANSI_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")


def split_content_lines(content: str) -> list[str]:
    """The lines ``content`` displays as (``[""]`` when it's blank).

    Trailing whitespace isn't content: ``"a\\n"`` is one line. The box, the
    echo and the repaint all split here, so their line counts agree.
    """
    return content.rstrip().split('\n')


def truncate_to_lines(
    content: str,
    max_lines: int,
    suffix: str = "...",
    overflow: Overflow = "head",
) -> str:
    """
    Truncate content to max_lines, marking the cut with suffix.

    Args:
        content: The content to truncate.
        max_lines: Maximum number of lines to keep.
        suffix: Marker for the cut (default: "...").
        overflow: Which end to keep: "head" (first lines, marker after
            them) or "tail" (last lines, marker before them).

    Returns:
        Truncated content with the marker if over limit, otherwise
        content.rstrip().
    """
    lines = split_content_lines(content)
    if len(lines) <= max_lines:
        return content.rstrip()
    if overflow == "tail":
        return suffix + '\n' + '\n'.join(lines[-max_lines:])
    return '\n'.join(lines[:max_lines]) + '\n' + suffix


def truncate_ansi_to_lines(
    content: str, max_lines: int, overflow: Overflow = "head"
) -> str:
    """
    Truncate ANSI-formatted content to max_lines, keeping styles intact.

    Keeping the head, an ANSI reset (``\\033[0m``) precedes the ``...``
    marker so styles don't leak into it. Keeping the tail, the SGR codes of
    the cut-off lines are replayed after the marker, restoring the style
    state the kept lines were written in (e.g. a color opened earlier).

    Args:
        content: The ANSI-formatted content to truncate.
        max_lines: Maximum number of lines to keep.
        overflow: Which end to keep: "head" or "tail".

    Returns:
        Truncated content if over limit, otherwise content.rstrip().
    """
    if overflow == "head":
        return truncate_to_lines(content, max_lines, suffix="\033[0m...")
    lines = split_content_lines(content)
    if len(lines) <= max_lines:
        return content.rstrip()
    state = "".join(ANSI_SGR_RE.findall("\n".join(lines[:-max_lines])))
    return "...\n" + state + "\n".join(lines[-max_lines:])


def format_exception_detail(exc: BaseException) -> str:
    """Format an exception as "Type: message", or just "Type" if message is empty."""
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
