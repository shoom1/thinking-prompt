"""
Dialog system for ThinkingPromptSession.

Provides dialogs that integrate with the existing Application layout, shown
two ways: as a box floating over the session, or inline, as rows under the
prompt. This avoids the issues with prompt_toolkit's built-in dialog
shortcuts, which create their own Application and cause rendering conflicts.

Example usage:

    # Built-in dialogs
    result = await session.yes_no_dialog("Confirm", "Are you sure?")
    await session.message_dialog("Info", "Operation completed.")
    choice = await session.choice_dialog("Action", "What to do?", ["Save", "Discard"])

    # A dialog built with arguments
    result = await session.show_dialog(Dialog(
        "Custom",
        "Enter your choice:",
        [ButtonConfig("OK", result=True), ButtonConfig("Cancel", result=False)],
    ))

    # A custom dialog via subclass
    class MyDialog(Dialog):
        title = "My Dialog"

        def build_body(self):
            return Label("Custom content")

        def get_buttons(self):
            return [ButtonConfig("OK", result=True)]

    result = await session.show_dialog(MyDialog())
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    cast,
)

from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import AnyFormattedText
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout import AnyContainer, Container, Float, HSplit, to_container
from prompt_toolkit.layout.containers import is_container
from prompt_toolkit.widgets import Label

from ._text import format_exception_detail
from .dialog_box import BoxPresenter
from .dialog_inline import InlinePresenter, InlineView
from .dialog_scroll import ScrollRegion, focusable_windows
from .fields import AlignValues, ChecklistField, Field, RadioField, _check_align_values, _Form
from .types import Placement, check_placement

if TYPE_CHECKING:
    from .session import ThinkingPromptSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ButtonConfig:
    """
    A dialog button.

    Attributes:
        text: Button label text.
        result: Value the dialog returns when this button is clicked.
        focused: If True, this button gets initial focus (the first one wins).
        style: Optional extra style for the button.
        handler: Optional function run on click instead of returning
            ``result``. It decides what happens: call ``set_result(...)`` or
            ``cancel()`` on the dialog to close it, or return without closing
            (e.g. while input fails validation).
    """
    text: str
    result: Any = None
    focused: bool = False
    style: str = ""
    handler: Callable[[], None] | None = None

    def __post_init__(self) -> None:
        if self.handler is not None and self.result is not None:
            raise ValueError(
                "ButtonConfig takes a result or a handler, not both: a handler "
                "decides the result itself (dialog.set_result(...))."
            )
        if inspect.iscoroutinefunction(self.handler):
            raise TypeError(
                "ButtonConfig handler must be a regular function, not async: "
                "start async work from it (e.g. asyncio.ensure_future(...)) "
                "and call dialog.set_result(...) when it's done."
            )


class _NotPassed:
    """Type of the marker for Dialog() arguments that weren't passed."""

    def __repr__(self) -> str:
        return "<not passed>"


# Dialog() leaves an option at its class default unless the argument is
# passed. None can't mark "not passed": it's a meaningful value for
# escape_result, width and max_height.
_NOT_PASSED = _NotPassed()


class Dialog:
    """
    A dialog shown over the running session that returns a result.

    Build one with arguments for simple dialogs, or subclass it and
    override build_body() / get_buttons() for custom ones. It's drawn as a
    box (prompt_toolkit's ``Dialog`` widget) or inline, as rows under the
    prompt (see ``placement``); this class holds what the dialog asks and
    returns: the result, Escape handling and the options below.

    The class attributes are the only defaults: constructor arguments
    override them per instance, subclasses override them as class attributes.

    Attributes:
        title: Title, shown in the box's frame or as the first inline row
            (default: none).
        body: Text (str, HTML, ANSI, FormattedText), shown in a Label, or
            any prompt_toolkit container.
        buttons: ButtonConfigs (default: none). A dialog needs something to
            focus: at least one button, fields, or a focusable body (e.g. a
            TextArea, closed with Escape).
        fields: Form fields shown under the body: TextField, CheckboxField,
            SelectField, DropdownField, ChecklistField, RadioField,
            ChoiceField. Their
            keys must be unique; ``values`` holds what they're set to. Read
            when the dialog is created: setting it afterwards changes nothing.
        align_values: Where field values start: "labels" (default: two
            columns after the longest label or description), "right" (the
            row's right edge) or a column number (longer labels cut with "…").
        escape_result: What Escape and cancel() return (default None).
        escapable: If False, Escape does nothing (default True).
        width: None/0 = auto, >0 = preferred width (never narrower than
            the buttons), -1 = full width (box only).
        max_height: The most rows the dialog takes, all of it counted (a
            box's border, title and buttons; an inline dialog's title,
            body, actions and hint); content that doesn't fit scrolls.
            None (default): the terminal's rows less the prompt's. Without
            it, an inline dialog also keeps its rows and actions within 12.
        placement: "box" (a framed dialog floating over the rows between
            the prompt and the status bar, scrolling what doesn't fit, or
            centered when those are fewer than its smallest size), "inline"
            (those rows themselves), or None (default) for the session's
            ``dialog_placement``.

    Example:
        # Built with arguments
        ok = await session.show_dialog(Dialog(
            "Delete?",
            "This can't be undone.",
            [ButtonConfig("Delete", result=True), ButtonConfig("Keep", result=False)],
            escapable=False,
        ))

        # Subclassed
        class LoginDialog(Dialog):
            title = "Login"
            fields = [TextField("user", "Username")]

            def get_buttons(self):
                return [
                    ButtonConfig("Login", handler=self.on_login),
                    ButtonConfig("Cancel", handler=self.cancel),
                ]

            def on_login(self):
                if self.values["user"]:  # stays open while empty
                    self.set_result(self.values)
    """

    title: str = ""
    body: AnyFormattedText | AnyContainer = ""
    buttons: Sequence[ButtonConfig] = ()
    # Form fields, under the body (see thinking_prompt.fields).
    fields: Sequence[Field] = ()
    # Where field values start: "labels", "right" or a column.
    align_values: AlignValues = "labels"
    escape_result: Any = None
    escapable: bool = True
    width: int | None = None
    # The most rows the dialog takes; what doesn't fit scrolls. None: the
    # terminal's rows less the prompt's.
    max_height: int | None = None
    # "box", "inline", or None for the session's dialog_placement.
    placement: Placement | None = None

    def __init__(
        self,
        title: str | _NotPassed = _NOT_PASSED,
        body: AnyFormattedText | AnyContainer | _NotPassed = _NOT_PASSED,
        buttons: Sequence[ButtonConfig] | _NotPassed = _NOT_PASSED,
        *,
        escape_result: Any = _NOT_PASSED,
        escapable: bool | _NotPassed = _NOT_PASSED,
        width: int | None | _NotPassed = _NOT_PASSED,
        max_height: int | None | _NotPassed = _NOT_PASSED,
        placement: Placement | None | _NotPassed = _NOT_PASSED,
        fields: Sequence[Field] | _NotPassed = _NOT_PASSED,
        align_values: AlignValues | _NotPassed = _NOT_PASSED,
    ) -> None:
        if not isinstance(placement, _NotPassed):
            check_placement(placement, optional=True)

        passed = {
            "title": title,
            "body": body,
            "buttons": buttons,
            "escape_result": escape_result,
            "escapable": escapable,
            "width": width,
            "max_height": max_height,
            "placement": placement,
            "fields": fields,
            "align_values": align_values,
        }
        for name, value in passed.items():
            if not isinstance(value, _NotPassed):
                setattr(self, name, value)
        if self.max_height is not None and self.max_height < 1:
            raise ValueError(f"max_height must be at least 1, got {self.max_height!r}")
        # One control per field, holding its value from now on (values).
        _check_align_values(self.align_values)
        self._form = _Form(self.fields)

        self._result_future: asyncio.Future | None = None
        self._manager: DialogManager | None = None
        # The placement this dialog is (or was last) shown with, resolved by
        # DialogManager; _content() lays the fields out for it.
        self._placement: Placement = "box"

    def build_body(self) -> AnyContainer:
        """
        Build the dialog body.

        Default: ``body`` itself if it's a container, otherwise ``body``
        shown as text in a Label. Override for custom content. The fields,
        if any, are shown under it.
        """
        body = self.body
        if is_container(body):
            return body
        return Label(text=cast("AnyFormattedText", body))

    @property
    def values(self) -> dict[str, Any]:
        """Each field's current value by key, in field order ({} without
        fields): what the fields hold now, before, while or after the dialog
        is shown. Read it from a button handler to return it."""
        return self._form.values

    def _content(self) -> tuple[Container | None, Container | None]:
        """What a presenter shows between the title and the buttons, and
        where the cursor starts in it when no button asks for it.

        The content: the body (unless it's an empty text body), then the
        fields laid out for the placement; None for neither. The start: the
        first thing in the body that takes focus, else the first field's
        start (a radio list's picked option); None for neither.
        """
        _check_align_values(self.align_values)
        body = to_container(self.build_body()) if self._has_body() else None
        body_stops = focusable_windows(body) if body is not None else []
        # A ChoiceField with nothing else to focus is always picking, and
        # Enter presses the first button.
        self._form.set_alone(not body_stops, self._press_first_button)
        fields = self._form.container(self._placement, self.align_values)
        start = body_stops[0] if body_stops else self._form.start()
        if fields is None:
            return body, start
        if self._placement == "inline":
            return (fields if body is None else HSplit([body, fields])), start
        # A box: Tab walks the body's windows and the fields as groups.
        tabs = self._form.tab_bindings(
            lambda: focusable_windows(body) if body is not None else []
        )
        if body is None:
            fields.key_bindings = merge_key_bindings([fields.key_bindings or KeyBindings(), tabs])
            return fields, start
        return HSplit([body, fields], key_bindings=tabs), start

    def _screen_floats(self) -> list[Float]:
        """Floats the fields need over the whole screen while the dialog is
        open as a box (a dropdown's menu). Called once, after _content()."""
        return self._form.floats()

    def get_buttons(self) -> list[ButtonConfig]:
        """
        Return the dialog's buttons.

        Default: ``buttons``. Override to compute them, e.g. with handlers
        bound to the instance.
        """
        return list(self.buttons)

    def set_result(self, value: Any) -> None:
        """
        Set the dialog result and close the dialog.

        Call this from button handlers to close the dialog
        and return a value.

        Args:
            value: The value to return from show_dialog().
        """
        if self._result_future and not self._result_future.done():
            self._result_future.set_result(value)

    def cancel(self) -> None:
        """
        Cancel the dialog and return escape_result.

        Convenience method for cancel buttons. Works whether or not the
        dialog is escapable.
        """
        self.set_result(self.escape_result)

    def _has_body(self) -> bool:
        """False for an empty text body: an inline dialog then skips the body row."""
        return type(self).build_body is not Dialog.build_body or self.body != ""

    def _is_editing(self) -> bool:
        """True while a field is being edited (a text field, an open menu):
        the cursor stays put meanwhile."""
        return self._form.is_editing()

    def _button_configs(self) -> list[ButtonConfig]:
        """get_buttons(), checked: every item must be a ButtonConfig.

        One check for every presentation, so a dialog built for 0.3 fails
        with a hint wherever it's shown.
        """
        configs = self.get_buttons()
        for cfg in configs:
            if not isinstance(cfg, ButtonConfig):
                raise TypeError(
                    "get_buttons() must return ButtonConfig items; got "
                    f"{type(cfg).__name__}. Use ButtonConfig(label, "
                    "handler=...) instead of (label, handler)."
                )
        return configs

    def _press_first_button(self) -> None:
        """Click the first button, as Enter on it would; nothing without
        buttons. Read when pressed: buttons can be set after the dialog
        is laid out."""
        configs = self._button_configs()
        if configs:
            self._click_handler(configs[0])()

    def _click_handler(self, cfg: ButtonConfig) -> Callable[[], None]:
        """What clicking ``cfg`` does: run its handler, or close with its result.

        A handler that raises is logged with its traceback and reported as
        an error line; the dialog stays open and the session keeps running.
        """
        handler = cfg.handler
        if handler is None:
            return lambda: self.set_result(cfg.result)

        def click() -> None:
            try:
                result = handler()
                if inspect.isawaitable(result):
                    if hasattr(result, "close"):
                        result.close()
                    raise TypeError(
                        "button handler returned an awaitable; handlers "
                        "must be regular functions"
                    )
            except Exception as exc:
                logger.error("Dialog button handler raised", exc_info=exc)
                if self._manager is not None:
                    detail = format_exception_detail(exc)
                    self._manager._session.add_error(f"Dialog button error: {detail}")

        return click

    def _prepare(self, manager: DialogManager, placement: Placement = "box") -> asyncio.Future:
        """Prepare the dialog for showing (called by DialogManager)."""
        self._manager = manager
        self._placement = placement
        loop = asyncio.get_running_loop()
        self._result_future = loop.create_future()
        return self._result_future


def _yes_no_dialog(
    title: str,
    text: str,
    yes_text: str = "Yes",
    no_text: str = "No",
    placement: Placement = "box",
    max_height: int | None = None,
) -> Dialog:
    """Yes/No confirmation: True or False; Escape returns False."""
    return Dialog(
        title,
        text,
        [ButtonConfig(yes_text, result=True), ButtonConfig(no_text, result=False)],
        escape_result=False,
        placement=placement,
        max_height=max_height,
    )


def _message_dialog(
    title: str,
    text: str,
    ok_text: str = "OK",
    placement: Placement = "box",
    max_height: int | None = None,
) -> Dialog:
    """A message with one button; returns None."""
    return Dialog(title, text, [ButtonConfig(ok_text)], placement=placement, max_height=max_height)


def _choice_dialog(
    title: str,
    text: str,
    choices: Sequence[str],
    placement: Placement = "box",
    max_height: int | None = None,
) -> Dialog:
    """One button per choice, returning its text; Escape returns None."""
    return Dialog(
        title,
        text,
        [ButtonConfig(choice, result=choice) for choice in choices],
        placement=placement,
        max_height=max_height,
    )


def _dropdown_dialog(
    title: str,
    text: str,
    options: Sequence[str],
    default: str | None = None,
    placement: Placement = "box",
    max_height: int | None = None,
) -> Dialog:
    """Pick one option; Cancel and Escape return None.

    Box: a radio list field with OK / Cancel; Tab goes from the list to OK.
    Inline: one numbered action per option. Either way the cursor starts on
    ``default``.
    """
    if not options:
        raise ValueError("dropdown_dialog() needs at least one option")
    if placement == "inline":
        return Dialog(
            title,
            text,
            [ButtonConfig(opt, result=opt, focused=opt == default) for opt in options],
            placement="inline",
            max_height=max_height,
        )

    # One option picked: the default, or the first when there's none (or
    # it isn't an option). The cursor starts on it.
    picked = default if default in options else options[0]
    dialog = Dialog(
        title,
        text,
        fields=[RadioField("choice", "", options=list(options), default=picked)],
        placement="box",
        max_height=max_height,
    )
    # Buttons set after construction: OK's handler needs the dialog itself.
    dialog.buttons = [
        ButtonConfig("OK", handler=lambda: dialog.set_result(dialog.values["choice"])),
        ButtonConfig("Cancel"),
    ]
    return dialog


def _checklist_dialog(
    title: str,
    text: str,
    options: Sequence[str],
    defaults: Sequence[str] = (),
    placement: Placement = "box",
    max_height: int | None = None,
) -> Dialog:
    """Check any number of options, one per line: OK returns the checked ones
    (in option order), Cancel and Escape None."""
    if not options:
        raise ValueError("checklist_dialog() needs at least one option")
    dialog = Dialog(
        title,
        text,
        fields=[ChecklistField("checked", "", options=list(options), default=tuple(defaults))],
        placement=placement,
        max_height=max_height,
    )
    # Buttons set after construction: OK's handler needs the dialog itself.
    dialog.buttons = [
        ButtonConfig("OK", handler=lambda: dialog.set_result(dialog.values["checked"])),
        ButtonConfig("Cancel"),
    ]
    return dialog


def _nothing_to_focus(dialog: Dialog) -> str:
    return (
        f"Dialog {dialog.title!r} has nothing to focus: give it a "
        "button (buttons=[ButtonConfig(...)]), fields, or a focusable body."
    )


class DialogManager:
    """
    Opens and closes dialogs within a ThinkingPromptSession.

    One dialog at a time: it claims the slot, waits for the result (cancelled
    if the app exits) and always restores focus to the prompt. Drawing is
    delegated to a presenter picked by the dialog's placement: BoxPresenter
    floats a framed dialog over the layout, InlinePresenter fills the
    layout's inline slot.

    The DialogManager is created lazily by ThinkingPromptSession
    when dialogs are first used.
    """

    def __init__(self, session: ThinkingPromptSession) -> None:
        self._session = session
        self._visible = False  # a dialog is open
        self._current_dialog: Dialog | None = None
        self._injected = False
        self._box = BoxPresenter(session)
        self._inline = InlinePresenter()

        # Create and register key bindings
        self._key_bindings = self._create_key_bindings()

    @property
    def inline_view(self) -> InlineView | None:
        """The open inline dialog, if any: the session's inline slot shows it."""
        return self._inline.view

    def box_rows(self, width: int, max_rows: int) -> int:
        """Rows the open box dialog takes; 0 when none is open. The session's
        inline slot reserves them."""
        return self._box.rows(width, max_rows)

    def _create_key_bindings(self) -> KeyBindings:
        """Escape, and the keys that scroll a text body that doesn't fit:
        PgUp/PgDn, and in a box also ↑↓ (its buttons use ←→ and Tab)."""
        kb = KeyBindings()

        @kb.add("escape", filter=Condition(lambda: self._visible))
        def handle_escape(event: Any) -> None:
            dialog = self._current_dialog
            if dialog and dialog.escapable:
                dialog.set_result(dialog.escape_result)

        text_overflows = Condition(self._text_overflows)
        in_box = Condition(lambda: self._box.view is not None)

        @kb.add("pageup", filter=text_overflows)
        def page_up(event: Any) -> None:
            self._scroll_text(pages=-1)

        @kb.add("pagedown", filter=text_overflows)
        def page_down(event: Any) -> None:
            self._scroll_text(pages=1)

        # Inline, ↑↓ are the cursor's: RowNavigator's own up/down, bound on
        # the dialog's container, outrank these app-level bindings anyway;
        # in_box says the intent.
        @kb.add("up", filter=text_overflows & in_box)
        def line_up(event: Any) -> None:
            self._scroll_text(lines=-1)

        @kb.add("down", filter=text_overflows & in_box)
        def line_down(event: Any) -> None:
            self._scroll_text(lines=1)

        return kb

    def _text_region(self) -> ScrollRegion | None:
        """The open dialog's text body (box or inline), which scrolls by keys;
        None when no dialog is open or its body has cursor stops."""
        if self._box.view is not None:
            return self._box.view.text_region
        if self._inline.view is not None:
            return self._inline.view.text_region
        return None

    def _text_overflows(self) -> bool:
        region = self._text_region()
        return self._visible and region is not None and region.overflows

    def _scroll_text(self, *, lines: int = 0, pages: int = 0) -> None:
        region = self._text_region()
        if region is not None:
            region.scroll(lines)
            region.page(pages)

    def _inject_float_container(self) -> None:
        """Install the box dialogs' float and the Escape binding (one-time)."""
        if self._injected:
            return

        self._box.install()

        # Merge key bindings with existing app key bindings
        existing_kb = self._session.app.key_bindings
        if existing_kb:
            self._session.app.key_bindings = merge_key_bindings([
                existing_kb,
                self._key_bindings,
            ])
        else:
            self._session.app.key_bindings = self._key_bindings

        self._injected = True

    async def show(self, dialog: Dialog) -> Any:
        """
        Show a dialog and wait for result.

        Args:
            dialog: The Dialog to show.

        Returns:
            The result value set by the dialog (via button click or Escape).

        Raises:
            RuntimeError: If the session isn't running (not started yet, or
                ended): only the running app can answer a dialog, so it
                would wait forever. Also if a dialog is already being
                shown: a second one would orphan the first one's result
                future, leaving its awaiter hung forever.
            asyncio.CancelledError: If the app exits while the dialog is
                open (e.g. one opened from a background task).
            TypeError: If ``dialog`` isn't a Dialog.
            ValueError: If the dialog has nothing focusable (e.g. no buttons
                and a text body), or its placement isn't 'box' or 'inline'.

        Whatever the dialog raises while being built or opened, the
        manager is left closed, so later dialogs can still be shown.
        """
        if not isinstance(dialog, Dialog):
            if isinstance(dialog, type) and issubclass(dialog, Dialog):
                raise TypeError(
                    f"show_dialog() takes a Dialog instance, got the class "
                    f"{dialog.__qualname__}: call it, e.g. "
                    f"show_dialog({dialog.__qualname__}())."
                )
            t = type(dialog)
            name = t.__qualname__ if t.__module__ == "builtins" else f"{t.__module__}.{t.__qualname__}"
            raise TypeError(
                f"show_dialog() takes a thinking_prompt.Dialog, got {name}. "
                "(DialogConfig was removed in 0.4: use Dialog(title, body, "
                "buttons, ...).)"
            )

        # Only the running app can answer a dialog (its buttons and Escape
        # are key bindings). prompt_toolkit sets app.future for the length
        # of a run, so it also tells us when the app exits.
        app_done = self._session.app.future
        if not self._session.app.is_running or app_done is None or app_done.done():
            raise RuntimeError(
                "show_dialog() needs a running session: call it while run() "
                "or run_async() is running, e.g. from an input handler."
            )

        placement = (
            dialog.placement if dialog.placement is not None
            else self._session.dialog_placement
        )
        check_placement(placement)

        if self._current_dialog is not None:
            raise RuntimeError(
                "A dialog is already being shown. Wait for it to close "
                "before showing another one."
            )

        self._inject_float_container()

        # Everything after claiming the slot runs under the finally below:
        # if building or focusing the dialog raises (a bug in a custom
        # build_body, nothing focusable), the manager must not be left
        # believing a dialog is open — it would refuse every later one.
        self._current_dialog = dialog
        try:
            future = dialog._prepare(self, placement)
            target: AnyContainer | None
            if placement == "box":
                box = self._box.open(dialog)
                # A ButtonConfig(focused=True) button, else where the body's
                # cursor starts (its first focusable window, else the first
                # field; a radio list's picked option), else the widget's
                # first focusable element (a button).
                target = box.initial_focus or box.widget
            else:
                target = self._inline.open(dialog).focus

            self._visible = True
            if target is None:
                raise ValueError(_nothing_to_focus(dialog))
            try:
                self._session.app.layout.focus(target)
            except ValueError as exc:
                raise ValueError(_nothing_to_focus(dialog)) from exc
            # Keys typed before the first render find the dialog's key
            # bindings (set on containers, not controls) through the parent
            # links, which prompt_toolkit only refreshes when it redraws.
            self._session.app.layout.update_parents_relations()
            self._session.app.invalidate()

            # Wait for result. If the app exits first, nobody can answer the
            # dialog any more: cancel it, so the awaiter gets CancelledError
            # instead of waiting forever.
            def abandon(_app_done: object) -> None:
                if not future.done():
                    future.cancel()

            app_done.add_done_callback(abandon)
            try:
                result = await future
            finally:
                app_done.remove_done_callback(abandon)
        finally:
            # Hide dialog and restore focus
            self._visible = False
            self._current_dialog = None
            self._box.close()
            self._inline.close()
            self._session.app.layout.focus(self._session.default_buffer)
            self._session.app.invalidate()

        return result
