#!/usr/bin/env python3
"""
Test script demonstrating the dialog system in thinking_prompt.

This example shows:
1. Built-in dialogs (yes_no, message, choice, dropdown)
2. Custom dialog via DialogConfig (composition)
3. Custom dialog via BaseDialog subclass

Run with: conda run -n thinking_prompt python examples/dialog_test.py
"""

import asyncio

from prompt_toolkit.layout import HSplit, VSplit, Window, D
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Label, TextArea

from thinking_prompt import (
    ThinkingPromptSession,
    AppInfo,
    DialogConfig,
    ButtonConfig,
    BaseDialog,
)


class LoginDialog(BaseDialog):
    """Example custom dialog with text input fields."""

    title = "Login"
    escape_result = None  # Escape returns None (cancel)

    def __init__(self):
        super().__init__()
        # Single input for simplicity (demonstrates custom dialog)
        self.username_input = TextArea(
            multiline=False,
            focusable=True,
            scrollbar=False,
            wrap_lines=False,
        )

    def build_body(self):
        # Simple single-row layout
        return VSplit([
            Window(
                content=FormattedTextControl("Username: "),
                width=10,
                dont_extend_width=True,
            ),
            self.username_input,
        ])

    def get_buttons(self):
        return [
            ("Login", self.on_login),
            ("Cancel", self.cancel),
        ]

    def on_login(self):
        username = self.username_input.text.strip()
        if not username:
            return  # Validation failed, don't close
        self.set_result({"username": username})


async def main():
    app_info = AppInfo(
        name="Dialog Demo",
        version="0.1.0",
        welcome_message=(
            "Commands:\n"
            "  settings  - Yes/No dialog\n"
            "  info      - Message dialog\n"
            "  action    - Choice dialog\n"
            "  theme     - Dropdown dialog\n"
            "  custom    - Custom DialogConfig\n"
            "  login     - Custom BaseDialog subclass\n"
            "  quit      - Exit"
        ),
    )

    session = ThinkingPromptSession(
        message=">>> ",
        app_info=app_info,
    )

    @session.on_input
    async def handle(text: str):
        text = text.strip().lower()

        if not text:
            return

        if text == "quit":
            session.exit()
            return

        # =====================================================================
        # Built-in Dialogs
        # =====================================================================

        if text == "settings":
            # Yes/No dialog
            result = await session.yes_no_dialog(
                title="Settings",
                text="Enable advanced mode?",
            )
            session.add_response(f"Advanced mode: {'enabled' if result else 'disabled'}")
            return

        if text == "info":
            # Message dialog (just OK button)
            await session.message_dialog(
                title="Information",
                text="This is an informational message.\nPress OK to continue.",
            )
            session.add_response("Message acknowledged")
            return

        if text == "action":
            # Choice dialog (multiple buttons)
            result = await session.choice_dialog(
                title="Select Action",
                text="What would you like to do?",
                choices=["Save", "Discard", "Cancel"],
            )
            if result:
                session.add_response(f"Selected action: {result}")
            else:
                session.add_response("Action cancelled (Escape pressed)")
            return

        if text == "theme":
            # Dropdown dialog (radio list selection)
            result = await session.dropdown_dialog(
                title="Select Theme",
                text="Choose a color theme:",
                options=["Light", "Dark", "System", "High Contrast"],
                default="System",
            )
            if result:
                session.add_response(f"Theme set to: {result}")
            else:
                session.add_response("Theme selection cancelled")
            return

        # =====================================================================
        # Custom Dialogs
        # =====================================================================

        if text == "custom":
            # Custom dialog via DialogConfig (composition pattern)
            config = DialogConfig(
                title="Custom Dialog",
                body="This dialog was created using DialogConfig.\nChoose an option:",
                buttons=[
                    ButtonConfig(text="Option A", result="a"),
                    ButtonConfig(text="Option B", result="b"),
                    ButtonConfig(text="Option C", result="c"),
                ],
                escape_result=None,  # Escape returns None
            )
            result = await session.show_dialog(config)
            if result:
                session.add_response(f"You chose: Option {result.upper()}")
            else:
                session.add_response("Custom dialog cancelled")
            return

        if text == "login":
            # Custom dialog via BaseDialog subclass
            dialog = LoginDialog()
            result = await session.show_dialog(dialog)
            if result:
                session.add_response(f"Login attempt: user='{result['username']}'")
            else:
                session.add_response("Login cancelled")
            return

        # Default: echo
        session.add_response(f"Unknown command: {text}")

    await session.run_async()


if __name__ == "__main__":
    asyncio.run(main())
