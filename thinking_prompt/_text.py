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


# What prompt_toolkit's ANSI parser reads as one: zero-width text (\x01 up
# to \x02), written as it is; an escape (ESC and the character after it:
# with "[", a control sequence, else the parser drops both); U+009B, a
# control sequence.
_SPECIAL = re.compile(r"[\x01\x1b\x9b]")
# A control sequence's parameters as the parser reads them, ASCII digits
# and ";" (it reads any digit, "²" too, then fails in int()); and as the
# grammar has them, with "?" and ":", and the bytes before its final one.
_PARAMETERS = re.compile(r"[0-9;]*")
_ANY_PARAMETERS = re.compile(r"[\x20-\x3f]*")
# A sequence longer than this, cut short at the text's end, is none: it's
# dropped, so a box doesn't hold it, and read it again, piece by piece.
_LONGEST_CUT = 256


def _parameters_end(text: str, start: int, pattern: re.Pattern[str]) -> int:
    """Where the parameters starting at ``start`` end: ``pattern``, and any
    digit that isn't ASCII (the parser reads it as a digit)."""
    def run_end(pos: int) -> int:
        match = pattern.match(text, pos)
        return match.end() if match else pos

    end = run_end(start)
    while end < len(text) and not text[end].isascii() and text[end].isdigit():
        end = run_end(end + 1)
    return end


def _color_code(parameters: str) -> str:
    """A color code with ``parameters`` (ASCII digits and ";"), each number
    at most 255: one over makes a color ("#12c0000") that raises at print,
    and int() refuses a string of more than 4,300 digits."""
    numbers = (
        "" if not n else "255" if len(n.lstrip("0")) > 3 else str(min(int(n), 255))
        for n in parameters.split(";")
    )
    return f"\x1b[{';'.join(numbers)}m"


def fixed_sequences(text: str, *, colors_only: bool = False) -> tuple[str, str]:
    """``text`` read as prompt_toolkit's ANSI parser reads it, each control
    sequence made safe for the parser, and what the text cuts short at its
    end (a sequence, or ESC alone), which the next text goes on.

    The parser raised on a digit that isn't ASCII (int("²")), so a
    sequence with one is dropped; a color code's numbers are at most 255.
    An escape that isn't a sequence (ESC and the character after it) is
    kept, for the parser to drop; zero-width text is kept as it is.
    ``colors_only``: only color codes are kept, every other sequence (a
    cursor move; one the grammar allows but the parser doesn't read, "?25l"
    too) and escape is dropped."""
    pieces: list[str] = []
    pos = 0
    while (found := _SPECIAL.search(text, pos)) is not None:
        start = found.start()
        pieces.append(text[pos:start])
        char = text[start]
        if char == "\x01":
            close = text.find("\x02", start)
            pos = len(text) if close < 0 else close + 1
            pieces.append(text[start:pos])
            continue
        if char == "\x1b":
            if start + 1 == len(text):
                return "".join(pieces), text[start:]
            if text[start + 1] != "[":
                pos = start + 2
                if not colors_only:
                    pieces.append(text[start:pos])
                continue
        begin = start + (1 if char == "\x9b" else 2)
        end = _parameters_end(text, begin, _ANY_PARAMETERS if colors_only else _PARAMETERS)
        if end == len(text):
            cut = text[start:]
            return "".join(pieces), cut if len(cut) <= _LONGEST_CUT else ""
        parameters, final, pos = text[begin:end], text[end], end + 1
        if final == "m" and _PARAMETERS.fullmatch(parameters):
            pieces.append(_color_code(parameters))
        elif not colors_only and parameters.replace(";", "").isascii():
            pieces.append(text[start:pos])
    pieces.append(text[pos:])
    return "".join(pieces), ""
