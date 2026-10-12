"""
Spinner: the animation on a thinking box's header line.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
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
        frames: The frames, in order (any sequence of strings; kept as a
            tuple). One frame is a static mark.
        interval: Seconds each frame is shown.

    Raises:
        ValueError: If there are no frames, or ``interval`` isn't positive.
    """

    frames: Sequence[str]
    interval: float = 0.1

    DOTS: ClassVar[Spinner]
    LINE: ClassVar[Spinner]
    ELLIPSIS: ClassVar[Spinner]

    def __post_init__(self) -> None:
        # Kept as a tuple, so a spinner is frozen (and hashable) through and through.
        object.__setattr__(self, "frames", tuple(self.frames))
        if not self.frames:
            raise ValueError("a Spinner needs frames; pass spinner=None for no spinner")
        if self.interval <= 0:
            raise ValueError(f"a Spinner's interval must be positive, got {self.interval!r}")


Spinner.DOTS = Spinner(("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"), 0.1)
Spinner.LINE = Spinner(("-", "\\", "|", "/"), 0.13)
Spinner.ELLIPSIS = Spinner((".  ", ".. ", "..."), 0.3)
