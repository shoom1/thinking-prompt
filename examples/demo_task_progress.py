#!/usr/bin/env python3
"""
Demo: Task progress with Rich-styled lines in the thinking box.

Shows how to use append_rich() and set_line_rich() to build a
multi-step task pipeline with colored status indicators:
  - Pending:   dim "○" marker
  - Active:    bold cyan "⟳" spinner
  - Completed: green "✓" checkmark

Run:
    python examples/demo_task_progress.py
"""
import asyncio

from thinking_prompt import ThinkingPromptSession, AppInfo


async def main():
    app_info = AppInfo(
        name="TaskProgress",
        version="1.0.0",
        thinking_text="Working",
        thinking_animation=("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"),
        thinking_animation_position="before",
        echo_thinking=False,
    )
    session = ThinkingPromptSession(
        app_info=app_info,
        message=">>> ",
        max_thinking_height=12,
    )

    @session.on_input
    async def handle(user_input: str):
        if not user_input.strip():
            return

        # Define task steps
        steps = [
            ("Load configuration", 0.4),
            ("Connect to database", 0.6),
            ("Fetch records", 0.8),
            ("Transform data", 1.0),
            ("Validate results", 0.5),
            ("Write output", 0.4),
        ]

        async with session.thinking(title="Processing") as ctx:
            # Render all steps as dim/pending
            for label, _ in steps:
                ctx.append_rich(f"[dim]  ○ {label}[/dim]\n")

            # Process each step
            for i, (label, duration) in enumerate(steps):
                # Mark current step as active (bold + spinner)
                ctx.set_line_rich(i, f"[bold cyan]  ⟳ {label}…[/bold cyan]")
                ctx.set_title(label)
                await asyncio.sleep(duration)
                # Mark completed (green checkmark)
                ctx.set_line_rich(i, f"[green]  ✓ {label}[/green]")

        session.add_response("All tasks completed successfully.")

    await session.run_async()


if __name__ == "__main__":
    print("Task Progress Demo")
    print("=" * 40)
    print("Type anything to see Rich-styled task progress.")
    print("Press Ctrl+C or Ctrl+D to exit.\n")
    asyncio.run(main())
