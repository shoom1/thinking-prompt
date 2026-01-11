#!/usr/bin/env python3
"""
Showcase Demo: A visually rich demo for screenshots and recordings.

This demo combines multiple features:
- Rich welcome message with ASCII art
- Animated thinking separator
- Progress indicators in the thinking box
- Console messages during thinking
- Markdown and code output

Perfect for creating demo GIFs and screenshots.

Run:
    python examples/demo_showcase.py
"""
import asyncio

from thinking_prompt import ThinkingPromptSession, AppInfo

# Check if rich is available for fancy welcome
try:
    from rich.panel import Panel
    from rich.text import Text
    from rich.console import Group
    from rich.align import Align
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


def create_welcome_message():
    """Create a fancy welcome message with ASCII art."""
    ascii_art = r"""
  _____ _     _       _    _               ____
 |_   _| |__ (_)_ __ | | _(_)_ __   __ _  | __ )  _____  __
   | | | '_ \| | '_ \| |/ / | '_ \ / _` | |  _ \ / _ \ \/ /
   | | | | | | | | | |   <| | | | | (_| | | |_) | (_) >  <
   |_| |_| |_|_|_| |_|_|\_\_|_| |_|\__, | |____/ \___/_/\_\
                                   |___/
    """

    if RICH_AVAILABLE:
        title = Text(ascii_art, style="bold cyan")
        subtitle = Text.from_markup(
            "\n[dim]A [bold]prompt_toolkit[/bold] extension for AI thinking visualization[/dim]\n"
            "\n[green]Features:[/green] Real-time streaming • Animated separator • Rich output\n"
            "[yellow]Controls:[/yellow] [bold]Ctrl+T[/bold] expand • [bold]Ctrl+C[/bold] cancel • [bold]Ctrl+D[/bold] exit\n"
        )
        content = Group(Align.center(title), Align.center(subtitle))
        return Panel(
            content,
            border_style="blue",
            padding=(1, 2),
        )
    else:
        return (
            ascii_art +
            "\n  A prompt_toolkit extension for AI thinking visualization\n"
            "\n  Features: Real-time streaming • Animated separator • Rich output\n"
            "  Controls: Ctrl+T expand • Ctrl+C cancel • Ctrl+D exit\n"
        )


async def main():
    app_info = AppInfo(
        name="ThinkingBox",
        version="0.1.1",
        welcome_message=create_welcome_message,
        thinking_text="Processing",
        thinking_animation=("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"),
        thinking_animation_position="before",
    )

    session = ThinkingPromptSession(
        app_info=app_info,
        message=">>> ",
        max_thinking_height=12,
    )

    @session.on_input
    async def handle(user_input: str):
        """Process user input with a rich demonstration."""
        if not user_input.strip():
            return

        # Special commands
        if user_input.strip().lower() == "help":
            session.add_response(
                "## Available Commands\n\n"
                "- **help** - Show this message\n"
                "- **demo** - Run a quick demo\n"
                "- *anything else* - Process with thinking visualization\n",
                markdown=True
            )
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
