#!/usr/bin/env python3
"""
Showcase Demo: A visually rich demo for screenshots and recordings.

This demo combines multiple features:
- Rich welcome message with ASCII art
- Animated thinking separator
- Progress indicators in the thinking box
- Console messages during thinking
- Markdown and code output
- Slash command completion dropdown

Perfect for creating demo GIFs and screenshots.

Run:
    python examples/demo_showcase.py
"""
import asyncio

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from thinking_prompt import ThinkingPromptSession, AppInfo
from thinking_prompt.settings_dialog import (
    SettingsDialog,
    DropdownItem,
    InlineSelectItem,
    TextItem,
    CheckboxItem,
)

# Check if rich is available for fancy welcome
try:
    from rich.panel import Panel
    from rich.text import Text
    from rich.console import Group
    from rich.align import Align
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class SlashCommandCompleter(Completer):
    """Completer that triggers for slash commands."""

    COMMANDS = {
        "help": "Show available commands",
        "confirm": "Yes/No dialog demo",
        "info": "Message dialog demo",
        "action": "Choice dialog demo",
        "theme": "Dropdown dialog demo",
        "settings": "Settings dialog demo",
        "clear": "Clear the screen",
    }

    def get_completions(self, document: Document, complete_event):
        """Yield completions when text starts with /."""
        text = document.text_before_cursor

        if not text.startswith("/"):
            return

        partial = text[1:].lower()

        for cmd, desc in self.COMMANDS.items():
            if cmd.startswith(partial):
                yield Completion(
                    text=f"/{cmd}",
                    start_position=-len(text),
                    display=f"/{cmd}",
                    display_meta=f" - {desc}",
                )


def create_welcome_message():
    """Create a fancy welcome message with ASCII art."""
    ascii_art = r"""  _____ _     _       _    _               ____
 |_   _| |__ (_)_ __ | | _(_)_ __   __ _  | __ )  _____  __
   | | | '_ \| | '_ \| |/ / | '_ \ / _` | |  _ \ / _ \ \/ /
   | | | | | | | | | |   <| | | | | (_| | | |_) | (_) >  <
   |_| |_| |_|_|_| |_|_|\_\_|_| |_|\__, | |____/ \___/_/\_\
                                   |___/"""

    if RICH_AVAILABLE:
        title = Text(ascii_art, style="bold cyan")
        subtitle = Text.from_markup(
            "\n[dim]A [bold]prompt_toolkit[/bold] extension for AI thinking visualization[/dim]\n"
            "[green]Features:[/green] Real-time streaming • Animated separator • Rich output\n"
            "[yellow]Controls:[/yellow] [bold]Ctrl+T[/bold] expand • [bold]Ctrl+C[/bold] cancel • [bold]Ctrl+D[/bold] exit • [bold]/[/bold] for commands"
        )
        content = Group(Align.center(title), Align.center(subtitle))
        return Panel(
            content,
            border_style="blue",
            padding=(0, 2),
        )
    else:
        return (
            ascii_art +
            "\n  A prompt_toolkit extension for AI thinking visualization\n"
            "  Features: Real-time streaming • Animated separator • Rich output\n"
            "  Controls: Ctrl+T expand • Ctrl+C cancel • Ctrl+D exit • / for commands"
        )


async def main():
    app_info = AppInfo(
        name="ThinkingBox",
        version="0.2.3",
        welcome_message=create_welcome_message,
        thinking_text="Processing",
        thinking_animation=("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"),
        thinking_animation_position="before",
    )

    session = ThinkingPromptSession(
        app_info=app_info,
        message=">>> ",
        max_thinking_height=12,
        completer=SlashCommandCompleter(),
        complete_while_typing=True,
        completions_menu_height=5,
    )

    @session.on_input
    async def handle(user_input: str):
        """Process user input with a rich demonstration."""
        if not user_input.strip():
            return

        text = user_input.strip()

        # Handle slash commands
        if text.startswith("/"):
            cmd = text[1:].lower()
        else:
            cmd = text.lower()

        # Special commands
        if cmd == "help":
            session.add_response(
                "## Available Commands\n\n"
                "Type `/` to see the completion menu, or use these commands:\n\n"
                "- **/help** - Show this message\n"
                "- **/confirm** - Yes/No dialog demo\n"
                "- **/info** - Message dialog demo\n"
                "- **/action** - Choice dialog demo\n"
                "- **/theme** - Dropdown dialog demo\n"
                "- **/settings** - Settings dialog demo\n"
                "- **/clear** - Clear the screen\n"
                "- *anything else* - Process with thinking visualization\n",
                markdown=True
            )
            return

        if cmd == "clear":
            session.clear()
            return

        # Dialog demonstrations
        if cmd == "confirm":
            result = await session.yes_no_dialog(
                title="Confirmation",
                text="Do you want to enable advanced mode?",
            )
            session.add_response(f"Advanced mode: **{'enabled' if result else 'disabled'}**", markdown=True)
            return

        if cmd == "info":
            await session.message_dialog(
                title="Information",
                text="ThinkingBox is ready for action!\nAll systems operational.",
            )
            session.add_response("Message acknowledged ✓")
            return

        if cmd == "action":
            result = await session.choice_dialog(
                title="Select Action",
                text="What would you like to do?",
                choices=["Save", "Discard", "Cancel"],
            )
            if result:
                session.add_response(f"Action selected: **{result}**", markdown=True)
            else:
                session.add_response("Action cancelled")
            return

        if cmd == "theme":
            result = await session.dropdown_dialog(
                title="Select Theme",
                text="Choose your preferred theme:",
                options=["Light", "Dark", "System", "High Contrast"],
                default="System",
            )
            if result:
                session.add_response(f"Theme set to: **{result}**", markdown=True)
            else:
                session.add_response("Theme selection cancelled")
            return

        if cmd == "settings":
            settings_items = [
                DropdownItem(
                    key="theme",
                    label="Theme",
                    description="Application color scheme",
                    options=["Light", "Dark", "System", "Solarized", "Nord"],
                    default="System",
                ),
                InlineSelectItem(
                    key="font_size",
                    label="Font Size",
                    options=["Small", "Medium", "Large", "Extra Large"],
                    default="Medium",
                ),
                TextItem(
                    key="username",
                    label="Username",
                    description="Your display name",
                    default="Guest",
                    edit_width=20,
                ),
                TextItem(
                    key="api_key",
                    label="API Key",
                    description="Your secret API key",
                    default="",
                    password=True,
                    edit_width=20,
                ),
                CheckboxItem(
                    key="notifications",
                    label="Enable Notifications",
                    description="Show desktop notifications",
                    default=True,
                ),
                CheckboxItem(
                    key="auto_save",
                    label="Auto Save",
                    default=False,
                ),
            ]
            dialog = SettingsDialog(
                title="Settings",
                items=settings_items,
            )
            result = await session.show_dialog(dialog)
            if result:
                changes = [f"- **{k}**: {v}" for k, v in result.items()]
                session.add_response(
                    "## Settings Updated\n\n" + "\n".join(changes),
                    markdown=True
                )
            else:
                session.add_response("Settings cancelled")
            return

        # Use context manager for thinking
        async with session.thinking() as content:
            # Phase 1: Initialization with spinner effect
            content.append("Initialization\n")

            steps = ["Loading modules", "Parsing input", "Allocating memory"]
            for i, step in enumerate(steps):
                content.append(f"  ✓ {step}\n")
                await asyncio.sleep(0.5)

            # Console message
            session.add_message("system", "Initialization complete")
            await asyncio.sleep(0.5)

            # Phase 2: Processing with progress bar
            total = 15
            for i in range(total + 1):
                bar_width = 30
                filled = int(bar_width * i / total)
                bar = "█" * filled + "░" * (bar_width - filled)
                percent = i * 100 // total

                # Update progress line in place
                if i > 0:
                    # Remove previous progress line
                    lines = content.text.split('\n')
                    lines = lines[:-2]  # Remove last line (progress) and empty
                    content.clear()
                    content.append('\n'.join(lines) + '\n')

                content.append(f"  [{bar}] {percent:3d}%\n")
                await asyncio.sleep(0.1)

            # Console success message
            session.add_success("Processing complete")
            await asyncio.sleep(0.5)

            # Phase 3: Analysis
            content.append("Analysis\n")
            findings = [
                f"Input length: {len(user_input)} characters",
                f"Word count: {len(user_input.split())} words",
                "Sentiment: Positive",
                "Complexity: Low",
            ]

            for finding in findings:
                content.append(f"  • {finding:<40}\n")
                await asyncio.sleep(0.4)

            await asyncio.sleep(0.3)

        # Final output with markdown
        session.add_response(
            f"**Analysis Complete**\n\n"
            f"> {user_input[:50]}{'...' if len(user_input) > 50 else ''}\n\n"
            f"**Summary:** Your input has been processed successfully.\n",
            markdown=True
        )

        # Show some code
        session.add_code(
            f'result = analyze("{user_input[:20]}...")\n'
            f'print(f"Processed {{len(result)}} items")',
            language="python"
        )

    # Run the session
    await session.run_async()


if __name__ == "__main__":
    asyncio.run(main())
