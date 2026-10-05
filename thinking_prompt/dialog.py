"""
Dialog system for ThinkingPromptSession.

Provides floating dialogs that integrate with the existing Application layout,
avoiding the issues with prompt_toolkit's built-in dialog shortcuts which
create their own Application and cause rendering conflicts.

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
from prompt_toolkit.layout import AnyContainer, HSplit
from prompt_toolkit.layout.containers import is_container
from prompt_toolkit.widgets import Label, RadioList

from .dialog_box import TERMINAL_TOO_SMALL, BoxPresenter
from .dialog_inline import InlinePresenter, InlineView
from .rows import OptionGroup, RowNavigator
from .types import Placement, check_placement, format_exception_detail

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
# escape_result, width, top and height.
_NOT_PASSED = _NotPassed()


class Dialog:
    """
    A dialog shown over the running session that returns a result.

    Build one with arguments for simple dialogs, or subclass it and
    override build_body() / get_buttons() for custom ones. It's drawn as a
    box (prompt_toolkit's ``Dialog`` widget); this class holds what the
    dialog asks and returns: the result, Escape handling and the options
    below.

    The class attributes are the only defaults: constructor arguments
    override them per instance, subclasses override them as class attributes.

    Attributes:
        title: Title shown in the frame (default: none).
        body: Text (str, HTML, ANSI, FormattedText), shown in a Label, or
            any prompt_toolkit container.
        buttons: ButtonConfigs (default: none). A dialog needs something to
            focus: at least one button, or a focusable body (e.g. a TextArea,
            closed with Escape).
        escape_result: What Escape and cancel() return (default None).
        escapable: If False, Escape does nothing (default True).
        width: None/0 = auto, >0 = preferred width, -1 = full width (box only).
        top: None = centered, >=0 = rows from top, <0 = rows from bottom (box only).
        height: Fixed total height; the body scrolls when it overflows (box only).
        placement: "box" (a framed dialog floating over the session),
            "inline" (rows between the prompt and the status bar), or None
            (default) for the session's ``dialog_placement``.

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

            def __init__(self):
                super().__init__()
                self.username = TextArea(multiline=False)

            def build_body(self):
                return HSplit([Label("Username:"), self.username])

            def get_buttons(self):
                return [
                    ButtonConfig("Login", handler=self.on_login),
                    ButtonConfig("Cancel", handler=self.cancel),
                ]

            def on_login(self):
                if self.username.text:  # stays open while empty
                    self.set_result({"user": self.username.text})
    """

    title: str = ""
    body: AnyFormattedText | AnyContainer = ""
    buttons: Sequence[ButtonConfig] = ()
    escape_result: Any = None
    escapable: bool = True
    width: int | None = None
    top: int | None = None
    # When set, the body is wrapped in a ScrollablePane so the dialog
    # renders in one shot instead of growing line-by-line as the renderer
    # measures content.
    height: int | None = None
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
        top: int | None | _NotPassed = _NOT_PASSED,
        height: int | None | _NotPassed = _NOT_PASSED,
        placement: Placement | None | _NotPassed = _NOT_PASSED,
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
            "top": top,
            "height": height,
            "placement": placement,
        }
        for name, value in passed.items():
            if not isinstance(value, _NotPassed):
                setattr(self, name, value)

        self._result_future: asyncio.Future | None = None
        self._manager: DialogManager | None = None
        # The placement this dialog is (or was last) shown with, resolved by
        # DialogManager; build_body() may read it (the settings dialog does).
        self._placement: Placement = "box"

    def build_body(self) -> AnyContainer:
        """
        Build the dialog body.

        Default: ``body`` itself if it's a container, otherwise ``body``
        shown as text in a Label. Override for custom content.
        """
        body = self.body
        if is_container(body):
            return body
        return Label(text=cast("AnyFormattedText", body))

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
        """True while a row of the body is being edited (e.g. a settings
        text field): the inline cursor stays put meanwhile."""
        return False

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
) -> Dialog:
    """Yes/No confirmation: True or False; Escape returns False."""
    return Dialog(
        title,
        text,
        [ButtonConfig(yes_text, result=True), ButtonConfig(no_text, result=False)],
        escape_result=False,
        placement=placement,
    )


def _message_dialog(
    title: str, text: str, ok_text: str = "OK", placement: Placement = "box"
) -> Dialog:
    """A message with one button; returns None."""
    return Dialog(title, text, [ButtonConfig(ok_text)], placement=placement)


def _choice_dialog(
    title: str, text: str, choices: Sequence[str], placement: Placement = "box"
) -> Dialog:
    """One button per choice, returning its text; Escape returns None."""
    return Dialog(
        title,
        text,
        [ButtonConfig(choice, result=choice) for choice in choices],
        placement=placement,
    )


def _dropdown_dialog(
    title: str,
    text: str,
    options: Sequence[str],
    default: str | None = None,
    placement: Placement = "box",
) -> Dialog:
    """Pick one option; Cancel and Escape return None.

    Box: a radio list with OK / Cancel. Inline: one numbered action per
    option, with the cursor starting on ``default``.
    """
    if not options:
        raise ValueError("dropdown_dialog() needs at least one option")
    if placement == "inline":
        return Dialog(
            title,
            text,
            [ButtonConfig(opt, result=opt, focused=opt == default) for opt in options],
            placement="inline",
        )

    radio: RadioList[str] = RadioList(values=[(opt, opt) for opt in options])
    if default is not None and default in options:
        radio.current_value = default

    dialog = Dialog(title, HSplit([Label(text=text), radio]), placement="box")
    # Buttons set after construction: OK's handler needs the dialog itself.
    dialog.buttons = [
        ButtonConfig("OK", handler=lambda: dialog.set_result(radio.current_value)),
        ButtonConfig("Cancel"),
    ]
    return dialog


def _checklist_dialog(
    title: str,
    text: str,
    options: Sequence[str],
    defaults: Sequence[str] = (),
    placement: Placement = "box",
) -> Dialog:
    """Check any number of options, one per line: OK returns the checked ones
    (in option order), Cancel and Escape None."""
    if not options:
        raise ValueError("checklist_dialog() needs at least one option")
    group = OptionGroup(options, multiple=True, selected=defaults)
    rows = [row.window for row in group.rows]
    # A box dialog's buttons take Tab, so the rows get their own ↑↓; inline,
    # the dialog's cursor walks the rows and the actions alike.
    navigation = RowNavigator(lambda: rows).key_bindings() if placement == "box" else None
    option_list = HSplit(rows, key_bindings=navigation)
    body = HSplit([Label(text=text), option_list]) if text else option_list

    dialog = Dialog(title, body, placement=placement)
    # Buttons set after construction: OK's handler needs the dialog itself.
    dialog.buttons = [
        ButtonConfig("OK", handler=lambda: dialog.set_result(group.checked)),
        ButtonConfig("Cancel"),
    ]
    return dialog


def _nothing_to_focus(dialog: Dialog) -> str:
    return (
        f"Dialog {dialog.title!r} has nothing to focus: give it a "
        "button (buttons=[ButtonConfig(...)]) or a focusable body."
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

    def _create_key_bindings(self) -> KeyBindings:
        """Create key bindings for dialog (Escape handler)."""
        kb = KeyBindings()

        @kb.add("escape", filter=Condition(lambda: self._visible))
        def handle_escape(event: Any) -> None:
            dialog = self._current_dialog
            if dialog and dialog.escapable:
                dialog.set_result(dialog.escape_result)

        return kb

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
            If the dialog's ``height`` is set and the terminal is too small
            to fit the minimum viable dialog, shows an error to the user and
            returns ``dialog.escape_result`` (or None if the dialog isn't
            escapable) without showing the dialog.

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

        effective_height: int | None = None
        if placement == "box":
            # Clamp dialog.height against terminal height (if height is set).
            clamped = self._box.effective_height(dialog)
            if clamped is TERMINAL_TOO_SMALL:
                return dialog.escape_result if dialog.escapable else None
            effective_height = clamped

        # Everything after claiming the slot runs under the finally below:
        # if building or focusing the dialog raises (a bug in a custom
        # build_body, nothing focusable), the manager must not be left
        # believing a dialog is open — it would refuse every later one.
        self._current_dialog = dialog
        try:
            future = dialog._prepare(self, placement)
            target: AnyContainer | None
            if placement == "box":
                box = self._box.open(dialog, effective_height)
                # A ButtonConfig(focused=True) button, else the first
                # focusable element of the dialog.
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
