#!/usr/bin/env python3
"""
Completer Demo: Shows slash-command autocompletion like Claude Code.

This demo demonstrates:
- Slash commands that trigger completion menu (type / to see suggestions)
- Arrow keys to navigate, Enter to select
- Regular text input without completion interference

Run:
    python examples/completer_demo.py
"""
import asyncio

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from thinking_prompt import ThinkingPromptSession, AppInfo


class SlashCommandCompleter(Completer):
    """Completer that only triggers for slash commands."""

    def __init__(self, commands: list[str]):
        """
        Initialize with a list of command names (without leading slash).

        Args:
            commands: List of command names, e.g., ["help", "settings", "quit"]
        """
        self.commands = sorted(commands)

    def get_completions(self, document: Document, complete_event):
        """Yield completions only when text starts with /."""
        text = document.text_before_cursor

        # Only complete if input starts with /
        if not text.startswith("/"):
            return

        # Get the partial command (without the leading /)
        partial = text[1:].lower()

        # Find matching commands
        for cmd in self.commands:
            if cmd.lower().startswith(partial):
                # Calculate how much to complete (replace everything after /)
                yield Completion(
                    text=f"/{cmd}",
                    start_position=-len(text),
                    display=f"/{cmd}",
                )


async def main():
    # Define slash commands
    commands = [
        "help",
        "settings",
        "clear",
        "history",
        "export",
        "import",
        "quit",
        "version",
        "status",
        "refresh",
    ]

    completer = SlashCommandCompleter(commands)

    app_info = AppInfo(
        name="CompleterDemo",
        version="1.0.0",
        welcome_message=(
            "Completer Demo - Type / to see available commands\n"
            "Commands: /help, /settings, /clear, /history, /export, /import, /quit, /version, /status, /refresh"
        ),
    )

    session = ThinkingPromptSession(
        app_info=app_info,
        message=">>> ",
        completer=completer,
        complete_while_typing=True,
        completions_menu_height=5,
    )

    @session.on_input
    async def handle(text: str):
        """Handle user input."""
        if not text.strip():
            return

        text = text.strip()

        # Handle slash commands
        if text.startswith("/"):
            cmd = text[1:].lower()

            if cmd == "help":
                session.add_response(
                    "## Available Commands\n\n"
                    "- **/help** - Show this help message\n"
                    "- **/settings** - Open settings dialog\n"
                    "- **/clear** - Clear the screen\n"
                    "- **/history** - Show command history\n"
                    "- **/export** - Export data\n"
                    "- **/import** - Import data\n"
                    "- **/quit** - Exit the application\n"
                    "- **/version** - Show version info\n"
                    "- **/status** - Show current status\n"
                    "- **/refresh** - Refresh data\n",
                    markdown=True
                )
                return

            if cmd == "quit":
                session.add_response("Goodbye!")
                raise KeyboardInterrupt

            if cmd == "version":
                session.add_response("CompleterDemo v1.0.0")
                return

            if cmd == "clear":
                session.clear()
                return

            if cmd in commands:
                async with session.thinking() as content:
                    content.append(f"Executing '/{cmd}'...\n")
                    await asyncio.sleep(0.5)
                    content.append("Done!\n")
                session.add_response(f"Command **/{cmd}** executed successfully.", markdown=True)
            else:
                session.add_response(f"Unknown command: /{cmd}. Type '/help' for available commands.")
        else:
            # Regular text input - echo it back
            async with session.thinking() as content:
                content.append("Processing your message...\n")
                await asyncio.sleep(0.3)
                content.append("Done!\n")
            session.add_response(f"You said: {text}")

    await session.run_async()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
