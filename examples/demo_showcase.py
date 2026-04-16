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
        "thinking": "Dynamic title + line editing demo",
        "confirm": "Yes/No dialog demo",
        "info": "Message dialog demo",
        "action": "Choice dialog demo",
        "theme": "Dropdown dialog demo",
        "tasks": "Multi-box task progress demo",
        "settings": "Settings dialog demo",
        "clear": "Clear the screen",
        "quit": "Exit the application",
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
        version="0.3.0",
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
        enable_status_bar=True,
        status_text="Ready",
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
                "- **/thinking** - Dynamic title + line editing demo\n"
                "- **/confirm** - Yes/No dialog demo\n"
                "- **/info** - Message dialog demo\n"
                "- **/action** - Choice dialog demo\n"
                "- **/theme** - Dropdown dialog demo\n"
                "- **/tasks** - Multi-box task progress demo\n"
                "- **/settings** - Settings dialog demo\n"
                "- **/clear** - Clear the screen\n"
                "- **/quit** - Exit the application\n"
                "- *anything else* - Process with thinking visualization\n",
                markdown=True
            )
            return

        if cmd == "clear":
            session.clear()
            return

        if cmd == "quit":
            session.exit()
            return

        if cmd == "thinking":
            # Dedicated demo: ctx.set_title() and ctx.set_line()
            async with session.thinking(title="Connecting") as ctx:
                # Phase 1 — connection steps
                endpoints = ["Auth service", "Data store", "Cache layer"]
                for ep in endpoints:
                    ctx.append(f"  ✓ {ep}\n")
                    await asyncio.sleep(0.4)

                await asyncio.sleep(0.3)

                # Phase 2 — downloading with a progress bar
                ctx.set_title("Downloading")
                total = 20
                bar_width = 30
                ctx.append(f"  [{'░' * bar_width}]   0%\n")
                for i in range(1, total + 1):
                    filled = int(bar_width * i / total)
                    bar = "█" * filled + "░" * (bar_width - filled)
                    percent = i * 100 // total
                    ctx.set_line(-1, f"  [{bar}] {percent:3d}%")
                    await asyncio.sleep(0.08)

                await asyncio.sleep(0.3)

                # Phase 3 — validating results (overwrite last status line)
                ctx.set_title("Validating")
                checks = ["Schema", "Integrity", "Permissions", "Signatures"]
                ctx.append(f"  ⏳ {checks[0]}…\n")
                for i, check in enumerate(checks):
                    ctx.set_line(-1, f"  ✓ {check}")
                    await asyncio.sleep(0.4)
                    if i + 1 < len(checks):
                        ctx.append(f"  ⏳ {checks[i + 1]}…\n")

                await asyncio.sleep(0.3)

            session.add_response(
                "**Demo complete** — used `ctx.set_title()` for separator changes "
                "and `ctx.set_line(-1, ...)` for in-place updates.",
                markdown=True,
            )
            return

        if cmd == "tasks":
            # Multi-box demo: task list + per-step detail boxes
            tasks = session.start_thinking(title="Tasks", order=100, max_lines=10)
            tasks.append_rich("[dim]  ○ Scanning files[/dim]\n")
            tasks.append_rich("[dim]  ○ Parsing AST[/dim]\n")
            tasks.append_rich("[dim]  ○ Running checks[/dim]\n")
            tasks.append_rich("[dim]  ○ Generating report[/dim]\n")

            # Step 1: Scan
            tasks.set_line_rich(0, "[bold cyan]  ⟳ Scanning files…[/bold cyan]")
            scan = session.start_thinking(title="Scan", max_lines=2)
            for pct in range(0, 101, 25):
                scan.set_line(0, f"  {pct}% scanned")
                await asyncio.sleep(0.3)
            scan.finish(echo_to_console=False, add_to_history=False)
            tasks.set_line_rich(0, "[green]  ✓ Scanning files[/green]")

            # Step 2: Parse
            tasks.set_line_rich(1, "[bold cyan]  ⟳ Parsing AST…[/bold cyan]")
            parse = session.start_thinking(title="Parse", max_lines=2)
            for i in range(4):
                parse.set_line(0, f"  Parsing module {i+1}/4...")
                await asyncio.sleep(0.4)
            parse.finish(echo_to_console=False, add_to_history=False)
            tasks.set_line_rich(1, "[green]  ✓ Parsing AST[/green]")

            # Step 3: Checks
            tasks.set_line_rich(2, "[bold cyan]  ⟳ Running checks…[/bold cyan]")
            checks = session.start_thinking(title="Checks", max_lines=2)
            for name in ["lint", "types", "security"]:
                checks.set_line(0, f"  Running {name}...")
                await asyncio.sleep(0.4)
            checks.finish(echo_to_console=False, add_to_history=False)
            tasks.set_line_rich(2, "[green]  ✓ Running checks[/green]")

            # Step 4: Report
            tasks.set_line_rich(3, "[bold cyan]  ⟳ Generating report…[/bold cyan]")
            await asyncio.sleep(0.5)
            tasks.set_line_rich(3, "[green]  ✓ Generating report[/green]")

            await asyncio.sleep(0.5)
            tasks.finish(echo_to_console=False, add_to_history=False)

            session.add_response(
                "**Demo complete** — used multiple thinking boxes: a task list "
                "with `order=100` pinned near the prompt, plus per-step detail boxes "
                "that appear and disappear as each step runs.",
                markdown=True,
            )
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
        async with session.thinking(title="Initializing") as ctx:
            # Phase 1: Initialization with spinner effect
            session.set_status("Phase 1/3: Initializing…")
            ctx.append("Initialization\n")

            steps = ["Loading modules", "Parsing input", "Allocating memory"]
            for i, step in enumerate(steps):
                ctx.append(f"  ✓ {step}\n")
                await asyncio.sleep(0.5)

            # Console message
            session.add_message("system", "Initialization complete")
            await asyncio.sleep(0.5)

            # Phase 2: Processing with progress bar
            ctx.set_title("Processing")
            session.set_status("Phase 2/3: Processing…")
            total = 15
            bar_width = 30
            ctx.append(f"  [{'░' * bar_width}]   0%\n")
            for i in range(1, total + 1):
                filled = int(bar_width * i / total)
                bar = "█" * filled + "░" * (bar_width - filled)
                percent = i * 100 // total

                # Update status bar with progress percentage
                if RICH_AVAILABLE:
                    session.set_status(Text.from_markup(
                        f"[bold]Phase 2/3:[/bold] Processing \\[{bar}] {percent:3d}%"
                    ))
                else:
                    session.set_status(f"Phase 2/3: Processing [{bar}] {percent:3d}%")

                # Update progress line in place
                ctx.set_line(-1, f"  [{bar}] {percent:3d}%")
                await asyncio.sleep(0.1)

            # Console success message
            session.add_success("Processing complete")
            await asyncio.sleep(0.5)

            # Phase 3: Analysis
            ctx.set_title("Analyzing")
            session.set_status("Phase 3/3: Analyzing…")
            ctx.append("Analysis\n")
            findings = [
                f"Input length: {len(user_input)} characters",
                f"Word count: {len(user_input.split())} words",
                "Sentiment: Positive",
                "Complexity: Low",
            ]

            for finding in findings:
                ctx.append(f"  • {finding:<40}\n")
                await asyncio.sleep(0.4)

            await asyncio.sleep(0.3)

        # Reset status bar after thinking
        session.set_status("Ready")

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
