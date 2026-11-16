"""
Text helpers shared by the thinking box, the transcript, error lines and
dialogs (internal).
"""
from __future__ import annotations

import re
from itertools import groupby

from prompt_toolkit.formatted_text.base import OneStyleAndTextTuple
from prompt_toolkit.utils import get_cwidth


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


def cut(text: str, columns: int) -> str:
    """``text`` in at most ``columns`` terminal columns, ending in "…" if cut."""
    if get_cwidth(text) <= columns:
        return text
    if columns < 1:
        return ""
    kept = ""
    for char in text:
        if get_cwidth(kept + char) > columns - 1:
            break
        kept += char
    return kept.rstrip() + "…"


def styled_lines(style: str, text: str) -> list[OneStyleAndTextTuple]:
    """``text`` in ``style``, its newlines unstyled: a newline written with
    a background color set makes the terminal fill the next line with it
    (a full-width bar after the line)."""
    fragments: list[OneStyleAndTextTuple] = []
    for i, piece in enumerate(text.split("\n")):
        if i:
            fragments.append(("", "\n"))
        if piece:
            fragments.append((style, piece))
    return fragments


# What starts a control sequence for prompt_toolkit's ANSI parser.
_CSI_START = re.compile(r"\x1b\[|\x9b")


def fixed_sequences(text: str, *, colors_only: bool = False) -> tuple[str, str]:
    """``text`` with each control sequence, as prompt_toolkit's ANSI parser
    reads one (ESC [ or U+009B, then digits and ";", then one character),
    made safe for it, and the sequence cut short at its end, if any (ESC
    alone too), which the next text goes on. The parser raised on a digit
    that isn't ASCII (int("²")), so such a sequence is dropped; and a
    color code's numbers are at most 255 (a component over makes a color,
    "#12c0000", that raises at print). ``colors_only``: every other
    sequence (a cursor move) is dropped too."""
    pieces: list[str] = []
    pos = 0
    while (start := _CSI_START.search(text, pos)) is not None:
        end = start.end()
        while end < len(text) and (text[end].isdigit() or text[end] == ";"):
            end += 1
        if end == len(text):
            break
        pieces.append(text[pos:start.start()])
        params, final, pos = text[start.end():end], text[end], end + 1
        if not params.replace(";", "").isascii():
            continue
        if final == "m":
            numbers = (str(min(int(n), 255)) if n else "" for n in params.split(";"))
            pieces.append(f"\x1b[{';'.join(numbers)}m")
        elif not colors_only:
            pieces.append(text[start.start():pos])
    rest = text[pos:]
    cut = _CSI_START.search(rest)
    if cut is None and rest.endswith("\x1b"):
        cut = re.search("\x1b$", rest)
    if cut is None:
        return "".join(pieces) + rest, ""
    return "".join(pieces) + rest[:cut.start()], rest[cut.start():]
