"""
Inline presentation of dialogs: rows between the prompt and the status bar.

A title, the body, one numbered row per button (ActionRow) and a key hint,
with one cursor (RowNavigator) over the body's rows and the actions. The
actions, and a body with cursor stops (settings rows, a check list, a text
field), scroll within MAX_ROWS rows; a body without (text) is drawn above
them at full height, clipped if the terminal is too short.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from prompt_toolkit.application.current import get_app
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.layout import Container, HSplit, VSplit, Window, to_container
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension

from .dialog_scroll import AtMost, ScrollRegion, focusable_windows
from .rows import ActionRow, RowControl, RowNavigator

if TYPE_CHECKING:
    from .dialog import Dialog

# Rows and actions scroll within this many rows; the title, a text body and
# the hint stay put.
MAX_ROWS = 12

# Hint line entries, in display order.
HINT_ORDER = ("↑↓ navigate", "←→ change", "Space toggle", "Enter select", "Esc cancel")


@dataclass
class InlineView:
    """A built inline dialog.

    Attributes:
        container: What the layout's inline slot shows.
        focus: What to focus when the dialog opens (None: nothing can take focus).
        actions: One ActionRow per ButtonConfig, in order.
        hint: The hint line's text ("" when there's nothing to say).
    """

    container: Container
    focus: Container | None
    actions: list[ActionRow]
    hint: str


def build_inline(dialog: Dialog) -> InlineView:
    """Build ``dialog`` as rows: title, body, numbered actions, hint."""
    configs = dialog._button_configs()
    number_width = len(str(len(configs)))
    actions = [
        ActionRow(number, cfg.text, dialog._click_handler(cfg), cfg.style, number_width)
        for number, cfg in enumerate(configs, start=1)
    ]
    body = to_container(dialog.build_body()) if dialog._has_body() else None

    def stops() -> list[Container]:
        body_stops = focusable_windows(body) if body is not None else []
        return [*body_stops, *(action.window for action in actions)]

    def at_first_stop() -> bool:
        first = stops()[:1]
        return bool(first) and get_app().layout.has_focus(first[0])

    rows: list[Container] = []
    if dialog.title:
        rows.append(_text_row("class:dialog-title", dialog.title))

    scrolled: list[Container] = []
    if body is not None:
        # A body with cursor stops scrolls with the actions; one without
        # (text) is drawn above them at full height, as a box dialog shows it.
        has_stops = bool(focusable_windows(body))
        part = scrolled if has_stops else rows
        part.append(body if has_stops else AtMost(body))
        if actions:
            part.append(_blank_row())
    scrolled.extend(action.window for action in actions)
    if scrolled:
        rows.append(AtMost(ScrollRegion(HSplit(scrolled), at_first_stop), MAX_ROWS))
    hint = _hint(dialog, stops())
    if hint:
        rows.append(_blank_row())
        rows.append(_text_row("class:dialog-hint", hint))

    navigator = RowNavigator(stops, is_editing=dialog._is_editing, tab=True, actions=actions)
    content = HSplit(rows, key_bindings=navigator.key_bindings())

    # Initial cursor: a ButtonConfig(focused=True) action, else the first stop.
    focused = next((a for a, cfg in zip(actions, configs) if cfg.focused), None)
    first = stops()
    focus = focused.window if focused is not None else (first[0] if first else None)

    # A one-column left margin.
    return InlineView(VSplit([Window(width=1), content]), focus, actions, hint)


def _blank_row() -> Window:
    """A blank separator row that a short terminal can take away."""
    return Window(height=Dimension(min=0, preferred=1, max=1))


def _text_row(style: str, text: str) -> Window:
    return Window(
        FormattedTextControl(FormattedText([(style, text)])),
        dont_extend_height=True,
        wrap_lines=True,
    )


def _hint(dialog: Dialog, stops: list[Container]) -> str:
    """The keys that do something in this dialog, in HINT_ORDER."""
    rows = [s.content for s in stops if isinstance(s, Window) and isinstance(s.content, RowControl)]
    keys: set[str] = set()
    if len(stops) >= 2:
        keys.add("↑↓ navigate")
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
