"""
Text helpers shared by the thinking box, the transcript and error lines
(internal).
"""
from __future__ import annotations

from itertools import groupby

from prompt_toolkit.formatted_text.base import OneStyleAndTextTuple


def coalesce(fragments: list[OneStyleAndTextTuple]) -> list[OneStyleAndTextTuple]:
    """Merge adjacent fragments with identical style; drop empty text.

    ANSI parsing produces ~one fragment per character; coalescing keeps
    memory and repaint cost proportional to styled runs instead. A run's
    text is joined once (added to a fragment at a time, it's copied each
    time).
    """
    out: list[OneStyleAndTextTuple] = []
    # A run of fragments in one style; 3-tuples (mouse handlers) aren't merged.
    for style, run in groupby(
        (frag for frag in fragments if frag[1]),
        lambda frag: frag[0] if len(frag) == 2 else None,
    ):
        if style is None:
            out.extend(run)
        else:
            out.append((style, "".join(frag[1] for frag in run)))
    return out


def format_exception_detail(exc: BaseException) -> str:
    """Format an exception as "Type: message", or just "Type" if message is empty."""
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
