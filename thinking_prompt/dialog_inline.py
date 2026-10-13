"""
Inline presentation of dialogs: rows between the prompt and the status bar.

A title, the body, one numbered row per button (ActionRow) and a key hint,
with one cursor (RowNavigator) over the body's rows and the actions. The
rows share the dialog's cap (_Sizes): the actions, and a body with cursor
stops (settings rows, a check list, a text field), scroll in one region
that follows the cursor; a body without (text) scrolls in its own region
above them, with PgUp/PgDn.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from prompt_toolkit.application.current import get_app
from prompt_toolkit.formatted_text import FormattedText, StyleAndTextTuples, to_formatted_text
from prompt_toolkit.layout import Container, HSplit, VSplit, Window, to_container
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension

from .dialog_scroll import AtMost, ScrollRegion, dialog_cap, focusable_windows, terminal_rows
from .rows import ActionRow, RowControl, RowNavigator

if TYPE_CHECKING:
    from .dialog import Dialog

# Without max_height, rows and actions scroll within this many rows; the
# title, a text body and the hint stay put.
MAX_ROWS = 12

# Hint line entries, in display order.
HINT_ORDER = (
    "↑↓ navigate",
    "PgUp/PgDn scroll",
    "←→ change",
    "Space toggle",
    "Enter select",
    "Esc cancel",
)


@dataclass
class InlineView:
    """A built inline dialog.

    Attributes:
        container: What the layout's inline slot shows.
        focus: What to focus when the dialog opens (None: nothing can take focus).
        actions: One ActionRow per ButtonConfig, in order.
        hint_text: The hint line's text, worked out at each redraw.
        text_region: The text body's region (a body with no cursor stops),
            which scrolls by keys; None otherwise.
    """

    container: Container
    focus: Container | None
    actions: list[ActionRow]
    hint_text: Callable[[], str]
    text_region: ScrollRegion | None = None

    @property
    def hint(self) -> str:
        """The hint line's text now ("" when there's nothing to say)."""
        return self.hint_text()


class _Sizes:
    """How an inline dialog's rows share its cap (dialog_cap): the fixed rows
    (title, hint, blank rows) first, then the region of cursor stops and
    actions, so they stay reachable, then a text body. Without max_height
    the region keeps to MAX_ROWS."""

    def __init__(
        self, max_height: int | None, region: ScrollRegion | None, text: ScrollRegion | None
    ) -> None:
        self.fixed: list[Container] = []
        self._max_height = max_height
        self._region = region
        self._text = text

    def _cap(self) -> int:
        return dialog_cap(self._max_height, terminal_rows())

    def _room(self, width: int) -> int:
        """Rows left after the fixed rows."""
        cap = self._cap()
        return cap - sum(row.preferred_height(width, cap).preferred for row in self.fixed)

    def region(self, width: int) -> int:
        room = self._room(width) - (1 if self._text is not None else 0)
        if self._max_height is None:
            room = min(room, MAX_ROWS)
        return max(1, room)

    def text(self, width: int) -> int:
        used = 0
        if self._region is not None:
            wanted = self._region.preferred_height(width, self._cap()).preferred
            used = min(wanted, self.region(width))
        return max(1, self._room(width) - used)


def build_inline(dialog: Dialog) -> InlineView:
    """Build ``dialog`` as rows: title, body, numbered actions, hint."""
    configs = dialog._button_configs()
    number_width = len(str(len(configs)))
    actions = [
        ActionRow(number, cfg.text, dialog._click_handler(cfg), cfg.style, number_width)
        for number, cfg in enumerate(configs, start=1)
    ]
    body = to_container(dialog.build_body()) if dialog._has_body() else None
    has_stops = body is not None and bool(focusable_windows(body))

    def stops() -> list[Container]:
        body_stops = focusable_windows(body) if body is not None else []
        return [*body_stops, *(action.window for action in actions)]

    def at_first_stop() -> bool:
        first = stops()[:1]
        return bool(first) and get_app().layout.has_focus(first[0])

    # A body with cursor stops scrolls with the actions; one without (text)
    # scrolls in a region of its own, above them.
    text = ScrollRegion(body) if body is not None and not has_stops else None
    scrolled: list[Container] = []
    if body is not None and has_stops:
        scrolled.append(body)
        if actions:
            scrolled.append(_blank_row())
    scrolled.extend(action.window for action in actions)
    region = ScrollRegion(HSplit(scrolled), at_first_stop) if scrolled else None

    sizes = _Sizes(dialog.max_height, region, text)
    rows: list[Container] = []

    def fixed(row: Container) -> None:
        rows.append(row)
        sizes.fixed.append(row)

    if dialog.title:
        fixed(_text_row("class:dialog-title", dialog.title))
    if text is not None:
        rows.append(AtMost(text, sizes.text))
        if actions:
            fixed(_blank_row())
    if region is not None:
        rows.append(AtMost(region, sizes.region))

    def hint() -> str:
        return _hint(dialog, stops(), text)

    if hint() or text is not None:
        fixed(_blank_row())
        fixed(_text_row("class:dialog-hint", hint))

    navigator = RowNavigator(stops, is_editing=dialog._is_editing, tab=True, actions=actions)
    content = HSplit(rows, key_bindings=navigator.key_bindings())

    # Initial cursor: a ButtonConfig(focused=True) action, else the first stop.
    focused = next((a for a, cfg in zip(actions, configs) if cfg.focused), None)
    first = stops()
    focus = focused.window if focused is not None else (first[0] if first else None)

    # A one-column left margin.
    return InlineView(VSplit([Window(width=1), content]), focus, actions, hint, text)


def _blank_row() -> Window:
    """A blank separator row that a short terminal can take away."""
    return Window(height=Dimension(min=0, preferred=1, max=1))


def _text_row(style: str, text: str | Callable[[], str]) -> Window:
    """A row of ``text`` (or what ``text()`` returns at each redraw), wrapped."""

    def fragments() -> FormattedText:
        return FormattedText([(style, text() if callable(text) else text)])

    control = _LiveText(fragments) if callable(text) else FormattedTextControl(fragments)
    return Window(control, dont_extend_height=True, wrap_lines=True)


class _LiveText(FormattedTextControl):
    """Text worked out each time it's drawn, not once per render. The hint
    depends on whether the text region overflows, which it learns while
    drawing, after the rows are sized; a once-per-render text would show the
    previous state and, with nothing else changing, stay stale."""

    def _get_formatted_text_cached(self) -> StyleAndTextTuples:
        return to_formatted_text(self.text, self.style)


def _hint(dialog: Dialog, stops: list[Container], text: ScrollRegion | None) -> str:
    """The keys that do something in this dialog now, in HINT_ORDER."""
    rows = [s.content for s in stops if isinstance(s, Window) and isinstance(s.content, RowControl)]
    keys: set[str] = set()
    if len(stops) >= 2:
        keys.add("↑↓ navigate")
    if text is not None and text.overflows:
        keys.add("PgUp/PgDn scroll")
    for row in rows:
        keys |= row.hints
    if rows:
        keys.add("Enter select")
    if dialog.escapable:
        keys.add("Esc cancel")
    return " · ".join(key for key in HINT_ORDER if key in keys)


class InlinePresenter:
    """Shows inline dialogs in the session layout's inline slot."""

    def __init__(self) -> None:
        self.view: InlineView | None = None

    def open(self, dialog: Dialog) -> InlineView:
        self.view = build_inline(dialog)
        return self.view

    def close(self) -> None:
        self.view = None
