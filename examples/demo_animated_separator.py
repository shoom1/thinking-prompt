#!/usr/bin/env python3
"""
Demo: Animated thinking separator.

This demo showcases the configurable animated separator above the thinking box.
Different animations can be configured: spinner (default), dots, arrows, etc.

Run:
    python examples/demo_animated_separator.py
"""
import asyncio

from thinking_prompt import ThinkingPromptSession, AppInfo


async def main():
    # Different animation configurations to demonstrate
    configs = [
        {
            "name": "Default (spinner)",
            "app_info": AppInfo(
                name="AnimatedDemo",
                version="1.0.0",
                # Default: thinking_text="Thinking"
                # Default: thinking_animation=("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
                # Default: thinking_animation_position="before"
            ),
        },
        {
            "name": "Dots after text",
            "app_info": AppInfo(
                name="AnimatedDemo",
                version="1.0.0",
                thinking_text="Processing",
                thinking_animation=(".  ", ".. ", "..."),
                thinking_animation_position="after",
            ),
        },
        {
            "name": "Arrow animation",
            "app_info": AppInfo(
                name="AnimatedDemo",
                version="1.0.0",
                thinking_text="Loading",
                thinking_animation=("→  ", " → ", "  →", " → "),
                thinking_animation_position="after",
            ),
        },
        {
            "name": "Just spinner (no text)",
            "app_info": AppInfo(
                name="AnimatedDemo",
                version="1.0.0",
                thinking_text="",  # No text
                # Uses default spinner animation
            ),
        },
        {
            "name": "Static text (no animation)",
            "app_info": AppInfo(
                name="AnimatedDemo",
                version="1.0.0",
                thinking_text="Working",
                thinking_animation=(),  # Empty tuple = no animation
            ),
        },
    ]

    current_config_idx = [0]  # Use list for mutable closure

    def get_current_config():
        return configs[current_config_idx[0]]

    # Start with first config
    config = get_current_config()
    session = ThinkingPromptSession(
        app_info=config["app_info"],
        message=">>> ",
        max_thinking_height=5,
    )

    @session.on_input
    async def handle(user_input: str):
        """Process user input and show thinking animation."""
        cmd = user_input.strip().lower()

        if cmd == "next":
            # Cycle to next animation configuration
            current_config_idx[0] = (current_config_idx[0] + 1) % len(configs)
            session.add_message(
                "system",
                f"Switch to: {configs[current_config_idx[0]]['name']} "
                "(restart to see change)"
            )
            return

        if cmd == "list":
            session.add_message("system", "Available animation configs:")
            for i, cfg in enumerate(configs):
                marker = "→ " if i == current_config_idx[0] else "  "
                session.add_message("system", f"  {marker}{i+1}. {cfg['name']}")
            return

        if not cmd:
            return

        # Demo the thinking animation
        async with session.thinking() as content:
            content.append("Starting process...\n")
            await asyncio.sleep(0.5)

            for i in range(1, 6):
                content.append(f"Step {i}/5: Processing data chunk\n")
                await asyncio.sleep(0.3)

            content.append("\nCompleted successfully!\n")
            await asyncio.sleep(0.3)

        session.add_success(f"Processed: {user_input}")

    # Run the session
    await session.run_async()


if __name__ == "__main__":
    print("Animated Thinking Separator Demo")
    print("================================")
    print("Type anything to see the animated thinking separator.")
    print("Commands:")
    print("  list - Show available animation configurations")
    print("  next - Select next configuration (restart to apply)")
    print("Press Ctrl+C or Ctrl+D to exit.\n")
    asyncio.run(main())
