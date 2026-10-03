"""
Dialog system for ThinkingPromptSession.

Provides floating dialogs that integrate with the existing Application layout,
avoiding the issues with prompt_toolkit's built-in dialog shortcuts which
create their own Application and cause rendering conflicts.

Example usage:

    # Simple built-in dialogs
    result = await session.yes_no_dialog("Confirm", "Are you sure?")
    await session.message_dialog("Info", "Operation completed.")
    choice = await session.choice_dialog("Action", "What to do?", ["Save", "Discard"])

    # Custom dialog via composition
    config = DialogConfig(
        title="Custom",
        body="Enter your choice:",
        buttons=[
            ButtonConfig(text="OK", result=True),
            ButtonConfig(text="Cancel", result=False),
        ],
    )
    result = await session.show_dialog(config)

    # Custom dialog via subclass
    class MyDialog(BaseDialog):
        title = "My Dialog"

        def build_body(self):
            return Label("Custom content")

        def get_buttons(self):
            return [("OK", lambda: self.set_result(True))]

    result = await session.show_dialog(MyDialog())
"""
from __future__ import annotations

import asyncio
import logging
import warnings
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    cast,
)

from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import AnyFormattedText
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout import (
    AnyContainer,
    ConditionalContainer,
    DynamicContainer,
    Float,
    FloatContainer,
    HSplit,
    ScrollablePane,
    Window,
    to_container,
)
from prompt_toolkit.layout.containers import is_container
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import Button, Label, RadioList
from prompt_toolkit.widgets import Dialog as _DialogWidget

if TYPE_CHECKING:
    from .session import ThinkingPromptSession

logger = logging.getLogger(__name__)


# Legacy sentinel: escape_result=_UNSET used to be the (private) way to
# disable Escape. Deprecated in favor of escapable=False; still honored.
class _Unset:
    """Legacy escape_result sentinel meaning "Escape disabled" (deprecated)."""
    pass


_UNSET = _Unset()


# Sentinel returned by _compute_effective_height when the terminal is
# too small to show the dialog. Caller aborts without building the widget.
_TERMINAL_TOO_SMALL = object()


@dataclass
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


@dataclass
class DialogConfig:
    """
    Configuration for creating a simple dialog via composition.

    Attributes:
        title: Dialog title displayed in the border.
        body: Dialog body - either a string or a prompt_toolkit Container.
        buttons: List of ButtonConfig objects defining the buttons.
        escape_result: Value returned when Escape is pressed (default None).
        escapable: If False, Escape does nothing; only a button closes the
                   dialog. Default True, as for every other dialog.
        width: Optional fixed width for the dialog.
    """
    title: str
    body: str | AnyContainer
    buttons: list[ButtonConfig] = field(default_factory=list)
    escape_result: Any = None
    escapable: bool = True
    width: int | None = None


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
    override build_body() / get_buttons() for custom ones. prompt_toolkit's
    ``Dialog`` widget draws it; this class adds the result, Escape handling
    and the options below.

    The class attributes are the only defaults: constructor arguments
    override them per instance, subclasses override them as class attributes.

    Attributes:
        title: Title shown in the frame (default: none).
        body: Text (str, HTML, ANSI, FormattedText), shown in a Label, or
            any prompt_toolkit container.
        buttons: ButtonConfigs (default: one "OK" button returning None).
        escape_result: What Escape and cancel() return (default None).
        escapable: If False, Escape does nothing (default True).
        width: None/0 = auto, >0 = preferred width, -1 = full width.
        top: None = centered, >=0 = rows from top, <0 = rows from bottom.
        height: Fixed total height; the body scrolls when it overflows.

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
                    ButtonConfig("Login", handler=self.on_login, focused=True),
                    ButtonConfig("Cancel", handler=self.cancel),
                ]

            def on_login(self):
                if self.username.text:  # stays open while empty
                    self.set_result({"user": self.username.text})
    """

    title: str = ""
    body: AnyFormattedText | AnyContainer = ""
    buttons: Sequence[ButtonConfig] = (ButtonConfig("OK"),)
    escape_result: Any = None
    escapable: bool = True
    width: int | None = None
    top: int | None = None
    # When set, the body is wrapped in a ScrollablePane so the dialog
    # renders in one shot instead of growing line-by-line as the renderer
    # measures content.
    height: int | None = None

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
    ) -> None:
        passed = {
            "title": title,
            "body": body,
            "buttons": buttons,
            "escape_result": escape_result,
            "escapable": escapable,
            "width": width,
            "top": top,
            "height": height,
        }
        for name, value in passed.items():
            if not isinstance(value, _NotPassed):
                setattr(self, name, value)

        self._result_future: asyncio.Future | None = None
        self._widget: _DialogWidget | None = None
        self._manager: DialogManager | None = None
        # Populated by _build_widget. _initial_focus, when non-None, is the
        # Window the DialogManager focuses after the dialog opens (the first
        # ButtonConfig(focused=True)). _focused_button is the matching Button
        # widget; _buttons is the full list, for inspection and testing.
        self._buttons: list[Button] = []
        self._focused_button: Button | None = None
        self._initial_focus: Window | None = None

    def _get_width_dimension(self) -> Dimension | None:
        """Convert width setting to prompt_toolkit Dimension.

        Returns:
            None for auto-size, Dimension for preferred width.
        """
        if self.width is None or self.width == 0:
            return None  # Auto-size
        elif self.width == -1:
            # Max width - use large preferred with no max constraint
            return Dimension(preferred=9999)
        else:
            # Preferred width (allows shrinking if terminal is smaller)
            return Dimension(preferred=self.width)

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
        self.set_result(self._escape_value())

    def _escape_value(self) -> Any:
        """escape_result — never the legacy _UNSET sentinel (that means None)."""
        return None if isinstance(self.escape_result, _Unset) else self.escape_result

    def _escape_enabled(self) -> bool:
        """Whether Escape closes the dialog (escapable, and not legacy _UNSET)."""
        return self.escapable and not isinstance(self.escape_result, _Unset)

    # Chrome height = title bar (2) + button row (2) + padding (1) around the body.
    # Used when `height` is set to compute the body area from the total.
    _CHROME_HEIGHT = 5

    def _build_widget(self, effective_height: int | None = None) -> _DialogWidget:
        """Build the prompt_toolkit Dialog widget.

        Args:
            effective_height: Caller-computed height after any terminal
                clamping. Overrides ``self.height`` for body-wrapping
                purposes. None means use ``self.height`` directly.
        """
        body = self.build_body()

        # Pin body height so the Dialog renders in one shot (opt-in via
        # the ``height`` attribute). Overflow scrolls within the pane.
        h = effective_height if effective_height is not None else self.height
        if h is not None and h > 0:
            body_height = max(1, h - self._CHROME_HEIGHT)
            body = HSplit(
                [ScrollablePane(to_container(body), show_scrollbar=True)],
                height=Dimension.exact(body_height),
            )

        self._buttons = self._build_buttons()

        self._widget = _DialogWidget(
            title=self.title,
            body=body,
            buttons=self._buttons,
            width=self._get_width_dimension(),
            with_background=False,  # Use styled dialog, no light overlay
        )
        return self._widget

    def _build_buttons(self) -> list[Button]:
        """Build the prompt_toolkit Button widgets from get_buttons().

        One implementation for every dialog: each ButtonConfig's style and
        focused flag apply however the dialog was made.
        """
        widgets: list[Button] = []
        self._focused_button = None
        self._initial_focus = None
        for cfg in self.get_buttons():
            if not isinstance(cfg, ButtonConfig):
                raise TypeError(
                    "get_buttons() must return ButtonConfig items; got "
                    f"{type(cfg).__name__}. Use ButtonConfig(label, "
                    "handler=...) instead of (label, handler)."
                )
            button = Button(text=cfg.text, handler=self._click_handler(cfg))
            _apply_button_style(button, cfg.style)
            if cfg.focused and self._focused_button is None:
                self._focused_button = button
                self._initial_focus = button.window
            widgets.append(button)
        return widgets

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
                handler()
            except Exception as exc:
                logger.error("Dialog button handler raised", exc_info=exc)
                if self._manager is not None:
                    detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                    self._manager._session.add_error(f"Dialog button error: {detail}")

        return click

    def _prepare(self, manager: DialogManager) -> asyncio.Future:
        """Prepare the dialog for showing (called by DialogManager)."""
        self._manager = manager
        loop = asyncio.get_running_loop()
        self._result_future = loop.create_future()
        return self._result_future


# Transitional alias, removed in the next task (0.4 drops the old name).
BaseDialog = Dialog


def _apply_button_style(button: Button, extra_style: str) -> None:
    """Append ``extra_style`` to a Button's style classes.

    The Button widget builds its own style callable that toggles between
    ``class:button`` and ``class:button.focused`` based on focus. We wrap
    that callable to append the user's style so focus styling still works.
    """
    if not extra_style:
        return
    original = button.window.style
    if callable(original):
        def combined() -> str:
            return f"{original()} {extra_style}".strip()
        button.window.style = combined
    else:
        button.window.style = f"{original} {extra_style}".strip()


class _ConfigBasedDialog(Dialog):
    """Internal: a Dialog built from a DialogConfig (removed with DialogConfig)."""

    def __init__(self, config: DialogConfig) -> None:
        super().__init__(
            config.title,
            config.body,
            config.buttons,
            escape_result=config.escape_result,
            escapable=config.escapable,
            width=config.width,
        )


def _yes_no_dialog(
    title: str, text: str, yes_text: str = "Yes", no_text: str = "No"
) -> Dialog:
    """Yes/No confirmation: True or False; Escape returns False."""
    return Dialog(
        title,
        text,
        [ButtonConfig(yes_text, result=True), ButtonConfig(no_text, result=False)],
        escape_result=False,
    )


def _message_dialog(title: str, text: str, ok_text: str = "OK") -> Dialog:
    """A message with one button; returns None."""
    return Dialog(title, text, [ButtonConfig(ok_text)])


def _choice_dialog(title: str, text: str, choices: Sequence[str]) -> Dialog:
    """One button per choice, returning its text; Escape returns None."""
    return Dialog(title, text, [ButtonConfig(choice, result=choice) for choice in choices])


def _dropdown_dialog(
    title: str, text: str, options: Sequence[str], default: str | None = None
) -> Dialog:
    """A radio list of options: OK returns the selection, Cancel None."""
    if not options:
        raise ValueError("dropdown_dialog() needs at least one option")
    radio: RadioList[str] = RadioList(values=[(opt, opt) for opt in options])
    if default is not None and default in options:
        radio.current_value = default

    dialog = Dialog(title, HSplit([Label(text=text), radio]))
    # Buttons set after construction: OK's handler needs the dialog itself.
    dialog.buttons = [
        ButtonConfig("OK", handler=lambda: dialog.set_result(radio.current_value)),
        ButtonConfig("Cancel"),
    ]
    return dialog


class DialogManager:
    """
    Manages dialog display within a ThinkingPromptSession.

    This class handles:
    - Injecting a FloatContainer into the session's layout
    - Showing/hiding dialogs
    - Focus management
    - Escape key handling

    The DialogManager is created lazily by ThinkingPromptSession
    when dialogs are first used.
    """

    # Rows reserved below/above the dialog: prompt area, status bar, margin.
    # When a dialog's ``height`` is set, the effective height is clamped to
    # ``terminal_height - _TERMINAL_BUFFER_ROWS`` so the dialog doesn't
    # cover the prompt or overflow the screen.
    _TERMINAL_BUFFER_ROWS = 4

    # Smallest total dialog height (chrome + body) that's considered usable.
    # With _TERMINAL_BUFFER_ROWS = 4, this implies a minimum terminal height
    # of _MIN_DIALOG_HEIGHT + _TERMINAL_BUFFER_ROWS = 12 rows.
    _MIN_DIALOG_HEIGHT = 8

    def __init__(self, session: ThinkingPromptSession) -> None:
        self._session = session
        self._visible = False
        self._current_dialog: Dialog | None = None
        self._injected = False
        self._dialog_container = DynamicContainer(self._get_dialog_content)
        self._dialog_float: Float | None = None

        # Create and register key bindings
        self._key_bindings = self._create_key_bindings()

    def _get_dialog_content(self) -> AnyContainer:
        """Return current dialog widget or empty window."""
        if self._current_dialog and self._current_dialog._widget:
            return self._current_dialog._widget
        return Window()

    def _create_key_bindings(self) -> KeyBindings:
        """Create key bindings for dialog (Escape handler)."""
        kb = KeyBindings()

        @kb.add("escape", filter=Condition(lambda: self._visible))
        def handle_escape(event: Any) -> None:
            dialog = self._current_dialog
            if dialog and dialog._escape_enabled():
                dialog.set_result(dialog.escape_result)

        return kb

    def _inject_float_container(self) -> None:
        """Inject FloatContainer into session layout (one-time)."""
        if self._injected:
            return

        original_container = self._session.app.layout.container

        # Create initial Float with no positioning (centered)
        self._dialog_float = Float(
            content=ConditionalContainer(
                content=self._dialog_container,
                filter=Condition(lambda: self._visible),
            ),
            allow_cover_cursor=True,
        )

        float_container = FloatContainer(
            content=original_container,
            floats=[self._dialog_float],
        )

        self._session.app.layout.container = float_container

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

    async def show(self, dialog: DialogConfig | Dialog) -> Any:
        """
        Show a dialog and wait for result.

        Args:
            dialog: Either a DialogConfig or a BaseDialog subclass instance.

        Returns:
            The result value set by the dialog (via button click or Escape).
            If the dialog's ``height`` is set and the terminal is too small
            to fit the minimum viable dialog, shows an error to the user and
            returns ``dialog.escape_result`` (or None if the dialog isn't
            escapable) without showing the dialog.

        Raises:
            RuntimeError: If a dialog is already being shown. Showing a
                second dialog would orphan the first one's result future,
                leaving its awaiter hung forever.
            ValueError: If the dialog has nothing focusable (e.g. a
                ``DialogConfig`` with no buttons and a plain-text body).

        Whatever the dialog raises while being built or opened, the
        manager is left closed, so later dialogs can still be shown.
        """
        if self._current_dialog is not None:
            raise RuntimeError(
                "A dialog is already being shown. Wait for it to close "
                "before showing another one."
            )

        # Ensure float container is injected
        self._inject_float_container()

        # Convert DialogConfig to BaseDialog if needed
        if isinstance(dialog, DialogConfig):
            dialog = _ConfigBasedDialog(dialog)

        if isinstance(dialog.escape_result, _Unset):
            warnings.warn(
                "escape_result=_UNSET is deprecated; set escapable=False to "
                "disable Escape.",
                DeprecationWarning,
                stacklevel=3,
            )

        # Clamp dialog.height against terminal height (if height is set).
        effective_height = self._compute_effective_height(dialog)
        if effective_height is _TERMINAL_TOO_SMALL:
            return dialog.escape_result if dialog._escape_enabled() else None

        # Everything after claiming the slot runs under the finally below:
        # if building or focusing the dialog raises (a bug in a custom
        # build_body, nothing focusable), the manager must not be left
        # believing a dialog is open — it would refuse every later one.
        self._current_dialog = dialog
        try:
            future = dialog._prepare(self)
            dialog._build_widget(effective_height=effective_height)

            # Update Float positioning based on dialog's top attribute
            if self._dialog_float:
                if dialog.top is None:
                    # Center: no top or bottom constraint
                    self._dialog_float.top = None
                    self._dialog_float.bottom = None
                elif dialog.top >= 0:
                    # Offset from top
                    self._dialog_float.top = dialog.top
                    self._dialog_float.bottom = None
                else:
                    # Negative = offset from bottom
                    self._dialog_float.top = None
                    self._dialog_float.bottom = abs(dialog.top)

                # Pin Float height so prompt_toolkit allocates the full
                # height in one render frame instead of measuring dialog
                # content over multiple ticks.
                if effective_height is not None:
                    self._dialog_float.height = effective_height
                else:
                    self._dialog_float.height = None

            # Show dialog
            self._visible = True
            assert dialog._widget is not None  # _build_widget set this above
            try:
                self._session.app.layout.focus(dialog._widget)
            except ValueError as exc:
                raise ValueError(
                    f"Dialog {dialog.title!r} has no focusable element, so it "
                    "could never be closed. Give it at least one button."
                ) from exc
            # Override default focus when a button opted in via ButtonConfig.focused.
            if dialog._initial_focus is not None:
                self._session.app.layout.focus(dialog._initial_focus)
            self._session.app.invalidate()

            # Wait for result
            result = await future
        finally:
            # Hide dialog and restore focus
            self._visible = False
            self._current_dialog = None
            self._session.app.layout.focus(self._session.default_buffer)
            self._session.app.invalidate()

        return result

    def _compute_effective_height(self, dialog: Dialog) -> Any:
        """Clamp dialog.height to the terminal and return the value to use.

        Returns:
            - ``None`` if the dialog didn't request a fixed height.
            - ``_TERMINAL_TOO_SMALL`` sentinel if the terminal can't fit
              the minimum viable dialog; caller should abort with an
              error message.
            - otherwise the clamped height to pass through to build_widget
              and Float.height.
        """
        if dialog.height is None or dialog.height <= 0:
            return None

        import shutil
        term_height = shutil.get_terminal_size().lines
        max_allowed = term_height - self._TERMINAL_BUFFER_ROWS

        if max_allowed < self._MIN_DIALOG_HEIGHT:
            required = self._MIN_DIALOG_HEIGHT + self._TERMINAL_BUFFER_ROWS
            self._session.add_error(
                f"Not enough room to show dialog: need at least {required} "
                f"terminal rows, have {term_height}."
            )
            return _TERMINAL_TOO_SMALL

        return min(dialog.height, max_allowed)
