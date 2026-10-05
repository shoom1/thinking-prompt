"""
Inline presentation of dialogs: rows between the prompt and the status bar.

A title, the body, one numbered row per button (ActionRow) and a key hint,
with one cursor (RowNavigator) over the body's rows and the actions. The
body and actions scroll within MAX_ROWS rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.layout import (
    Container,
    HSplit,
    ScrollablePane,
    VSplit,
    Window,
    to_container,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.layout import walk
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.screen import Screen, WritePosition

from .rows import ActionRow, RowControl, RowNavigator

if TYPE_CHECKING:
    from .dialog import Dialog

# The body and actions scroll within this many rows; the title and hint stay put.
MAX_ROWS = 12

# Hint line entries, in display order.
HINT_ORDER = ("↑↓ navigate", "←→ change", "Space toggle", "Enter select", "Esc cancel")


class _AtMost(Container):
    """``content`` with its preferred height capped at ``rows``.

    ScrollablePane alone either prefers its content's full height or, given
    a height, prefers none at all.
    """

    def __init__(self, content: Container, rows: int) -> None:
        self.content = content
        self.rows = rows

    def reset(self) -> None:
        self.content.reset()

    def preferred_width(self, max_available_width: int) -> Dimension:
        return self.content.preferred_width(max_available_width)

    def preferred_height(self, width: int, max_available_height: int) -> Dimension:
        wanted = self.content.preferred_height(width, max_available_height)
        return Dimension(
            min=min(wanted.min, self.rows),
            max=self.rows,
            preferred=min(wanted.preferred, self.rows),
        )

    def write_to_screen(
        self,
        screen: Screen,
        mouse_handlers: MouseHandlers,
        write_position: WritePosition,
        parent_style: str,
        erase_bg: bool,
        z_index: int | None,
    ) -> None:
        self.content.write_to_screen(
            screen, mouse_handlers, write_position, parent_style, erase_bg, z_index
        )

    def get_children(self) -> list[Container]:
        return [self.content]


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
    actions = [
        ActionRow(number, cfg.text, dialog._click_handler(cfg), cfg.style)
        for number, cfg in enumerate(configs, start=1)
    ]
    body = to_container(dialog.build_body()) if dialog._has_body() else None

    def stops() -> list[Container]:
        body_stops = _focusable_windows(body) if body is not None else []
        return [*body_stops, *(action.window for action in actions)]

    scrolled: list[Container] = []
    if body is not None:
        scrolled.append(body)
        if actions:
            scrolled.append(Window(height=1))
    scrolled.extend(action.window for action in actions)

    rows: list[Container] = []
    if dialog.title:
        rows.append(_text_row("class:dialog-title", dialog.title))
    if scrolled:
        rows.append(_AtMost(ScrollablePane(HSplit(scrolled), show_scrollbar=False), MAX_ROWS))
    hint = _hint(dialog, stops())
    if hint:
        rows.append(Window(height=1))
        rows.append(_text_row("class:dialog-hint", hint))

    navigator = RowNavigator(stops, is_editing=dialog._is_editing, tab=True, actions=actions)
    content = HSplit(rows, key_bindings=navigator.key_bindings())

    # Initial cursor: a ButtonConfig(focused=True) action, else the first stop.
    focused = next((a for a, cfg in zip(actions, configs) if cfg.focused), None)
    first = stops()
    focus = focused.window if focused is not None else (first[0] if first else None)

    # A one-column left margin.
    return InlineView(VSplit([Window(width=1), content]), focus, actions, hint)


def _text_row(style: str, text: str) -> Window:
    return Window(
        FormattedTextControl(FormattedText([(style, text)])),
        dont_extend_height=True,
        wrap_lines=True,
    )


def _focusable_windows(container: Container) -> list[Container]:
    return [
        c for c in walk(container, skip_hidden=True)
        if isinstance(c, Window) and c.content.is_focusable()
    ]


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
