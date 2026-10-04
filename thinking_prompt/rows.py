"""
Dialog rows: focusable one-line controls that one cursor walks.

Inline dialogs are made of rows: numbered actions (ActionRow), check and
radio options (OptionRow) and the settings dialog's controls. Box dialogs use
the same rows for check lists and settings forms. RowNavigator moves the
cursor between them.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence

from prompt_toolkit.application.current import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import Container, Layout, Window
from prompt_toolkit.layout.controls import UIContent, UIControl

# Drawn in front of the row under the cursor (as in prompt_toolkit's choice()).
MARKER = "❯ "
NO_MARKER = "  "


def has_focus(window: Window, fallback: bool = False) -> bool:
    """Whether ``window`` has focus in the current app (``fallback`` if that can't be told)."""
    try:
        return get_app().layout.has_focus(window)
    except Exception:
        return fallback


class RowControl(UIControl):
    """A UIControl that is one row of a dialog.

    RowNavigator moves the cursor with ↑↓ and runs actions with the digits
    only while a RowControl has focus, so a body built from other widgets
    (a TextArea) keeps those keys.
    """

    @property
    def hints(self) -> frozenset[str]:
        """Keys this row adds to an inline dialog's hint line."""
        return frozenset()

    def is_focusable(self) -> bool:
        return True


class ActionRow(RowControl):
    """One numbered action of an inline dialog, e.g. ``❯ 1. Delete``.

    Enter runs ``on_select``: the dialog's click logic for that button.
    """

    def __init__(
        self, number: int, text: str, on_select: Callable[[], None], style: str = ""
    ) -> None:
        self.number = number
        self.text = text
        self.on_select = on_select
        self.style = style
        self.window = Window(self, height=1, dont_extend_height=True)
        self._key_bindings = KeyBindings()

        @self._key_bindings.add("enter")
        def _select(event: KeyPressEvent) -> None:
            self.on_select()

    def create_content(self, width: int, height: int) -> UIContent:
        selected = has_focus(self.window)
        style = "class:dialog-choice-selected" if selected else "class:dialog-choice"
        if self.style:
            style = f"{style} {self.style}"
        marker = MARKER if selected else NO_MARKER
        line: StyleAndTextTuples = [(style, f"{marker}{self.number}. {self.text}")]
        return UIContent(get_line=lambda i: line, line_count=1)

    def get_key_bindings(self) -> KeyBindings:
        return self._key_bindings


class OptionGroup:
    """The state of a check list (any number checked) or a radio list
    (at most one picked), with one OptionRow per option."""

    def __init__(
        self,
        options: Sequence[str],
        *,
        multiple: bool,
        selected: Sequence[str] = (),
        indent: int = 0,
    ) -> None:
        self.options = list(options)
        self.multiple = multiple
        self._selected: set[str] = set()
        self.select(selected)
        self.rows = [OptionRow(self, option, indent) for option in self.options]

    @property
    def checked(self) -> list[str]:
        """The selected options, in option order."""
        return [option for option in self.options if option in self._selected]

    @property
    def picked(self) -> str | None:
        """A radio list's selected option (None if none)."""
        checked = self.checked
        return checked[0] if checked else None

    def is_selected(self, option: str) -> bool:
        return option in self._selected

    def choose(self, option: str) -> None:
        """Toggle ``option`` (check list) or pick it (radio list)."""
        if self.multiple:
            self._selected ^= {option}
        else:
            self._selected = {option}

    def select(self, options: Sequence[str]) -> None:
        """Replace the selection. Unknown options are ignored; a radio list
        keeps only the first."""
        chosen = [option for option in options if option in self.options]
        self._selected = set(chosen if self.multiple else chosen[:1])


class OptionRow(RowControl):
    """One option of an OptionGroup: ``[x] search`` or ``(•) fast``.

    Space or Enter toggles it (check list) or picks it (radio list).
    """

    def __init__(self, group: OptionGroup, option: str, indent: int = 0) -> None:
        self.group = group
        self.option = option
        self.indent = indent
        self.window = Window(self, height=1, dont_extend_height=True)
        self._key_bindings = KeyBindings()

        @self._key_bindings.add("space")
        @self._key_bindings.add("enter")
        def _choose(event: KeyPressEvent) -> None:
            self.group.choose(self.option)

    @property
    def hints(self) -> frozenset[str]:
        return frozenset({"Space toggle"})

    def create_content(self, width: int, height: int) -> UIContent:
        selected = has_focus(self.window)
        marked = self.group.is_selected(self.option)
        mark = (
            ("[x]" if marked else "[ ]")
            if self.group.multiple
            else ("(•)" if marked else "( )")
        )
        label_style = "class:setting-label-selected" if selected else "class:setting-label"
        line: StyleAndTextTuples = [
            ("class:setting-indicator" if selected else "", MARKER if selected else NO_MARKER),
            ("", " " * self.indent),
            ("class:checkbox-mark", mark),
            (label_style, f" {self.option}"),
        ]
        return UIContent(get_line=lambda i: line, line_count=1)

    def get_key_bindings(self) -> KeyBindings:
        return self._key_bindings


class RowNavigator:
    """One cursor over an ordered list of focus stops.

    ↑↓ move to the previous/next stop and stop at the first and last. They
    act only while a RowControl has focus, so a body built from other widgets
    (a TextArea) keeps its own arrow keys. With ``tab=True``, Tab and
    Shift+Tab move too, from any stop: the way into and out of such a body.
    With ``actions``, digits 1–9 run those actions directly while a row has
    focus. Nothing moves while ``is_editing()`` is true.
    """

    def __init__(
        self,
        stops: Callable[[], Sequence[Container]],
        *,
        is_editing: Callable[[], bool] = lambda: False,
        tab: bool = False,
        actions: Sequence[ActionRow] = (),
    ) -> None:
        self._stops = stops
        self._is_editing = is_editing
        self._tab = tab
        self._actions = list(actions)

    def index(self, layout: Layout) -> int | None:
        """Position of the focused stop, or None if focus is elsewhere."""
        for i, stop in enumerate(self._stops()):
            if layout.has_focus(stop):
                return i
        return None

    def move(self, layout: Layout, delta: int) -> None:
        """Focus the stop ``delta`` away from the focused one, clamped to the ends."""
        stops = list(self._stops())
        current = self.index(layout)
        if current is None:
            return
        target = max(0, min(len(stops) - 1, current + delta))
        if target != current:
            layout.focus(stops[target])

    def key_bindings(self) -> KeyBindings:
        kb = KeyBindings()
        idle = Condition(lambda: not self._is_editing())
        on_row = Condition(lambda: isinstance(get_app().layout.current_control, RowControl))

        @kb.add("up", filter=idle & on_row)
        def _up(event: KeyPressEvent) -> None:
            self.move(event.app.layout, -1)

        @kb.add("down", filter=idle & on_row)
        def _down(event: KeyPressEvent) -> None:
            self.move(event.app.layout, 1)

        if self._tab:
            @kb.add("tab", filter=idle)
            def _next(event: KeyPressEvent) -> None:
                self.move(event.app.layout, 1)

            @kb.add("s-tab", filter=idle)
            def _previous(event: KeyPressEvent) -> None:
                self.move(event.app.layout, -1)

        for number, action in enumerate(self._actions[:9], start=1):
            kb.add(str(number), filter=idle & on_row)(self._runner(action))

        return kb

    @staticmethod
    def _runner(action: ActionRow) -> Callable[[KeyPressEvent], None]:
        def run(event: KeyPressEvent) -> None:
            action.on_select()

        return run
