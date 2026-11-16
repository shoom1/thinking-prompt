"""
Spinner: the animation on a thinking box's header line.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import KW_ONLY, dataclass
from typing import ClassVar


@dataclass(frozen=True)
class Spinner:
    """
    A thinking header's animation: its frames, and how long each is shown.

    Presets: ``Spinner.DOTS`` (braille, the default), ``Spinner.LINE``
    (ASCII only) and ``Spinner.ELLIPSIS``. Pass ``spinner=None`` instead
    for a header without one.

    Example:
        ThinkingPromptSession(spinner=Spinner.LINE)
        ThinkingPromptSession(spinner=Spinner(("◐", "◓", "◑", "◒"), interval=0.15))

    Args:
        frames: The frames, in order: a sequence of strs (a list or a
            tuple; kept as a tuple). One frame is a static mark.
        interval: Seconds each frame is shown (passed by name).

    Raises:
        ValueError: If ``frames`` isn't a sequence of strs (a str isn't:
            one frame is ``("|",)``) or is empty, or ``interval`` isn't a
            positive, finite number.
    """

    frames: Sequence[str]
    _: KW_ONLY
    interval: float = 0.1

    DOTS: ClassVar[Spinner]
    LINE: ClassVar[Spinner]
    ELLIPSIS: ClassVar[Spinner]

    def __post_init__(self) -> None:
        frames = self.frames
        # A str would be taken as its letters, a set in no fixed order.
        if (
            isinstance(frames, str)
            or not isinstance(frames, Sequence)
            or not all(isinstance(frame, str) for frame in frames)
        ):
            raise ValueError(f"a Spinner's frames must be a sequence of str, got {frames!r}")
        # Kept as a tuple, so a spinner is frozen (and hashable) through and through.
        object.__setattr__(self, "frames", tuple(frames))
        if not self.frames:
            raise ValueError("a Spinner needs frames; pass spinner=None for no spinner")
        interval = self.interval
        if not isinstance(interval, (int, float)) or isinstance(interval, bool):
            raise ValueError(f"a Spinner's interval must be a number of seconds, got {interval!r}")
        # Not just > 0: NaN compares false both ways, and infinity never redraws.
        if not (math.isfinite(interval) and interval > 0):
            raise ValueError(f"a Spinner's interval must be positive and finite, got {self.interval!r}")


Spinner.DOTS = Spinner(("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"), interval=0.1)
Spinner.LINE = Spinner(("-", "\\", "|", "/"), interval=0.13)
Spinner.ELLIPSIS = Spinner((".  ", ".. ", "..."), interval=0.3)
