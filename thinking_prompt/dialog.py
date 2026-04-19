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
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
)

from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    AnyContainer,
    ConditionalContainer,
    DynamicContainer,
    Float,
    HSplit,
    Window,
)
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import Button, Dialog, Label, RadioList

if TYPE_CHECKING:
    from .session import ThinkingPromptSession


# Sentinel value for "escape disabled"
class _Unset:
    """Sentinel for unset escape_result (meaning escape is disabled)."""
    pass


_UNSET = _Unset()


@dataclass
class ButtonConfig:
    """
    Configuration for a dialog button.

    Attributes:
        text: Button label text.
        result: Value returned when this button is clicked.
        focused: If True, this button gets initial focus.
        style: Optional style class for the button.
    """
    text: str
    result: Any = None
    focused: bool = False
    style: str = ""


@dataclass
class DialogConfig:
    """
    Configuration for creating a simple dialog via composition.

    Attributes:
        title: Dialog title displayed in the border.
        body: Dialog body - either a string or a prompt_toolkit Container.
        buttons: List of ButtonConfig objects defining the buttons.
        escape_result: Value returned when Escape is pressed.
                      Use _UNSET (default) to disable Escape key.
        width: Optional fixed width for the dialog.
    """
    title: str
    body: str | AnyContainer
    buttons: list[ButtonConfig] = field(default_factory=list)
    escape_result: Any = _UNSET
    width: int | None = None


class BaseDialog(ABC):
    """
    Base class for creating custom dialogs via subclassing.

    Subclass this to create dialogs with custom layout and behavior.
    Override build_body() and get_buttons() to define the dialog content.

    Attributes:
        title: Dialog title (class attribute or property).
        escape_result: Value returned when Escape is pressed.
                      Set to _UNSET to disable Escape key.

    Example:
        class LoginDialog(BaseDialog):
            title = "Login"
            escape_result = None  # Escape returns None

            def __init__(self):
                super().__init__()
                self.username = TextArea(multiline=False)

            def build_body(self):
                return HSplit([
                    Label("Username:"),
                    self.username,
                ])

            def get_buttons(self):
                return [
                    ("Login", self.on_login),
                    ("Cancel", self.cancel),
                ]

            def on_login(self):
                if self.username.text:
                    self.set_result({"user": self.username.text})
    """

    title: str = "Dialog"
    escape_result: Any = None
    width: int | None = None  # None/0=auto, >0=min width, -1=max width
    # Vertical position: None=center, 0+=from top, negative=from bottom
    top: int | None = None

    def __init__(self) -> None:
        self._result_future: asyncio.Future | None = None
        self._widget: Dialog | None = None
        self._manager: DialogManager | None = None

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

    @abstractmethod
    def build_body(self) -> AnyContainer:
        """
        Build and return the dialog body container.

        Override this method to define the dialog content.

        Returns:
            A prompt_toolkit Container for the dialog body.
        """
        pass

    def get_buttons(self) -> list[tuple[str, Callable[[], None]]]:
        """
        Return the list of buttons for the dialog.

        Override this method to define custom buttons.
        Each button is a tuple of (label, handler_callable).

        Returns:
            List of (label, handler) tuples.
        """
        return [("OK", lambda: self.set_result(None))]

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

        Convenience method for cancel buttons.
        """
        self.set_result(self.escape_result)

    def _build_widget(self) -> Dialog:
        """Build the prompt_toolkit Dialog widget."""
        body = self.build_body()
        buttons = [
            Button(text=text, handler=handler)
            for text, handler in self.get_buttons()
        ]

        self._widget = Dialog(
            title=self.title,
            body=body,
            buttons=buttons,
            width=self._get_width_dimension(),
            with_background=False,  # Use styled dialog, no light overlay
        )
        return self._widget

    def _prepare(self, manager: DialogManager) -> asyncio.Future:
        """Prepare the dialog for showing (called by DialogManager)."""
        self._manager = manager
        loop = asyncio.get_running_loop()
        self._result_future = loop.create_future()
        return self._result_future


class _ConfigBasedDialog(BaseDialog):
    """Internal dialog class that wraps a DialogConfig."""

    def __init__(self, config: DialogConfig) -> None:
        super().__init__()
        self._config = config
        self.title = config.title
        self.escape_result = config.escape_result

    def build_body(self) -> AnyContainer:
        body = self._config.body
        if isinstance(body, str):
            return Label(text=body)
        return body

    def get_buttons(self) -> list[tuple[str, Callable[[], None]]]:
        def _make_handler(result: Any) -> Callable[[], None]:
            return lambda: self.set_result(result)

        buttons: list[tuple[str, Callable[[], None]]] = []
        for btn in self._config.buttons:
            buttons.append((btn.text, _make_handler(btn.result)))
        return buttons


class _YesNoDialog(BaseDialog):
    """Built-in Yes/No confirmation dialog."""

    def __init__(
        self,
        title: str,
        text: str,
        yes_text: str = "Yes",
        no_text: str = "No",
    ) -> None:
        super().__init__()
        self.title = title
        self._text = text
        self._yes_text = yes_text
        self._no_text = no_text
        self.escape_result = False  # Escape returns False

    def build_body(self) -> AnyContainer:
        return Label(text=self._text)

    def get_buttons(self) -> list[tuple[str, Callable[[], None]]]:
        return [
            (self._yes_text, lambda: self.set_result(True)),
            (self._no_text, lambda: self.set_result(False)),
        ]


class _MessageDialog(BaseDialog):
    """Built-in message/alert dialog with OK button."""

    def __init__(
        self,
        title: str,
        text: str,
        ok_text: str = "OK",
    ) -> None:
        super().__init__()
        self.title = title
        self._text = text
        self._ok_text = ok_text
        self.escape_result = None  # Escape returns None (same as OK)

    def build_body(self) -> AnyContainer:
        return Label(text=self._text)

    def get_buttons(self) -> list[tuple[str, Callable[[], None]]]:
        return [(self._ok_text, lambda: self.set_result(None))]


class _ChoiceDialog(BaseDialog):
    """Built-in choice dialog with multiple buttons."""

    def __init__(
        self,
        title: str,
        text: str,
        choices: Sequence[str],
    ) -> None:
        super().__init__()
        self.title = title
        self._text = text
        self._choices = choices
        self.escape_result = None  # Escape returns None

    def build_body(self) -> AnyContainer:
        return Label(text=self._text)

    def get_buttons(self) -> list[tuple[str, Callable[[], None]]]:
        def _make_handler(choice: str) -> Callable[[], None]:
            return lambda: self.set_result(choice)

        buttons: list[tuple[str, Callable[[], None]]] = []
        for choice in self._choices:
            buttons.append((choice, _make_handler(choice)))
        return buttons


class _DropdownDialog(BaseDialog):
    """Built-in dropdown selection dialog using RadioList."""

    def __init__(
        self,
        title: str,
        text: str,
        options: Sequence[str],
        default: str | None = None,
    ) -> None:
        super().__init__()
        self.title = title
        self._text = text
        self._options = options
        self._default = default
        self.escape_result = None  # Escape returns None

        # Create RadioList with options
        values = [(opt, opt) for opt in options]
        self._radio_list = RadioList(values=values)

        # Set default selection
        if default and default in options:
            self._radio_list.current_value = default

    def build_body(self) -> AnyContainer:
        return HSplit([
            Label(text=self._text),
            self._radio_list,
        ])

    def get_buttons(self) -> list[tuple[str, Callable[[], None]]]:
        return [
            ("OK", self._on_ok),
            ("Cancel", self.cancel),
        ]

    def _on_ok(self) -> None:
        self.set_result(self._radio_list.current_value)


class DialogManager:
    """
    Manages dialog display within a ThinkingPromptSession.

    The Float and KeyBindings are constructed eagerly and exposed via
    properties so the session can wire them into the layout and
    Application at construction time. This avoids fragile post-hoc
    mutation of the live layout.
    """

    def __init__(self, session: ThinkingPromptSession) -> None:
        self._session = session
        self._visible = False
        self._current_dialog: BaseDialog | None = None
        self._dialog_container = DynamicContainer(self._get_dialog_content)

        # Float is wired into the layout's FloatContainer at session construction.
        # Visibility toggles via _visible; positioning is updated per show().
        self._dialog_float = Float(
            content=ConditionalContainer(
                content=self._dialog_container,
                filter=Condition(lambda: self._visible),
            ),
            allow_cover_cursor=True,
        )

        # Key bindings are merged into the Application at construction.
        self._key_bindings = self._create_key_bindings()

    @property
    def float(self) -> Float:
        """The Float to be added to the layout's root FloatContainer."""
        return self._dialog_float

    @property
    def key_bindings(self) -> KeyBindings:
        """KeyBindings to be merged into the Application."""
        return self._key_bindings

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
            if self._current_dialog:
                escape_result = self._current_dialog.escape_result
                if not isinstance(escape_result, _Unset):
                    self._current_dialog.set_result(escape_result)

        return kb

    async def show(self, dialog: DialogConfig | BaseDialog) -> Any:
        """
        Show a dialog and wait for result.

        Args:
            dialog: Either a DialogConfig or a BaseDialog subclass instance.

        Returns:
            The result value set by the dialog (via button click or Escape).
        """
        # Convert DialogConfig to BaseDialog if needed
        if isinstance(dialog, DialogConfig):
            dialog = _ConfigBasedDialog(dialog)

        # Prepare dialog
        self._current_dialog = dialog
        future = dialog._prepare(self)
        dialog._build_widget()

        # Update Float positioning based on dialog's top attribute
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

        # Show dialog
        self._visible = True
        assert dialog._widget is not None  # _build_widget set this above
        self._session.app.layout.focus(dialog._widget)
        self._session.app.invalidate()

        try:
            # Wait for result
            result = await future
        finally:
            # Hide dialog and restore focus
            self._visible = False
            self._current_dialog = None
            self._session.app.layout.focus(self._session.default_buffer)
            self._session.app.invalidate()

        return result
