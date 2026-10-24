#!/usr/bin/env python3
"""
Demo: Animated thinking separator.

This demo showcases the configurable animated separator above the thinking box.
Different animations can be configured: spinner (default), dots, arrows, etc.

A session's header settings are fixed when it is created, so switching
animation ends the session and starts a new one with the chosen settings.

Run:
    python examples/demo_animated_separator.py
"""
from __future__ import annotations

import asyncio

from thinking_prompt import ThinkingPromptSession, AppInfo, Spinner

# Different animation configurations to demonstrate (session options)
CONFIGS = [
    {
        "name": "Default (spinner)",
        "options": {
            # Default: thinking_title="Thinking"
            # Default: spinner=Spinner.DOTS
            # Default: spinner_position="before"
        },
    },
    {
        "name": "Dots after text",
        "options": {
            "thinking_title": "Processing",
            "spinner": Spinner.ELLIPSIS,
            "spinner_position": "after",
        },
    },
    {
        "name": "ASCII line",
        "options": {
            "thinking_title": "Working",
            "spinner": Spinner.LINE,
        },
    },
    {
        "name": "Arrow animation (custom frames and speed)",
        "options": {
            "thinking_title": "Loading",
            "spinner": Spinner(("→  ", " → ", "  →", " → "), interval=0.15),
            "spinner_position": "after",
        },
    },
    {
        "name": "Just spinner (no text)",
        "options": {
            "thinking_title": "",  # No text
            # Uses default spinner animation
        },
    },
    {
        "name": "Static text (no animation)",
        "options": {
            "thinking_title": "Working",
            "spinner": None,  # No spinner
        },
    },
]


async def run_config(index: int) -> int | None:
    """Run a session with CONFIGS[index]; return the config to switch to,
    or None when the user exits."""
    config = CONFIGS[index]
    session = ThinkingPromptSession(
        app_info=AppInfo(
            name="AnimatedDemo",
            version="1.0.0",
            welcome_message=f"Animation {index + 1}/{len(CONFIGS)}: {config['name']}",
        ),
        message=">>> ",
        max_thinking_height=5,
        **config["options"],
    )
    switch_to: list[int | None] = [None]  # Use list for mutable closure

    @session.on_input
    async def handle(user_input: str):
        """Process user input and show thinking animation."""
        cmd = user_input.strip().lower()

        if cmd == "next" or (cmd.isdigit() and 1 <= int(cmd) <= len(CONFIGS)):
            # Restart with the chosen configuration
            switch_to[0] = (index + 1) % len(CONFIGS) if cmd == "next" else int(cmd) - 1
            session.exit()
            return

        if cmd == "list":
            session.add_system("Available animation configs:")
            for i, cfg in enumerate(CONFIGS):
                marker = "→ " if i == index else "  "
                session.add_system(f"  {marker}{i+1}. {cfg['name']}")
            return

        if not cmd:
            return

        # Demo the thinking animation
        async with session.thinking() as content:
            content.append("Starting process...\n")
            await asyncio.sleep(1.0)

            for i in range(1, 6):
                content.append(f"Step {i}/5: Processing data chunk\n")
                await asyncio.sleep(0.8)

            content.append("\nCompleted successfully!\n")
            await asyncio.sleep(1.0)

        session.add_success(f"Processed: {user_input}")

    await session.run_async()
    return switch_to[0]


async def main():
    index: int | None = 0
    while index is not None:
        index = await run_config(index)


if __name__ == "__main__":
    print("Animated Thinking Separator Demo")
    print("================================")
    print("Type anything to see the animated thinking separator.")
    print("Commands:")
    print("  list - Show available animation configurations")
    print("  next - Switch to the next configuration")
    print(f"  1-{len(CONFIGS)}  - Switch to that configuration")
    print("Press Ctrl+C or Ctrl+D to exit.\n")
    asyncio.run(main())
