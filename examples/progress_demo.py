#!/usr/bin/env python3
"""
Progress demo showing dynamic thinking box content.

This demonstrates the callback-based thinking box where the content
updates dynamically - the callback returns different content each time
it's called.

Press Ctrl+T during thinking to expand the thinking box.
The thinking content is added to history when finish_thinking() is called.

Run:
    python examples/progress_demo.py
"""
import asyncio

from thinking_prompt import ThinkingPromptSession, AppInfo


async def main():
    app_info = AppInfo(name="ProgressDemo", version="1.0.0")
    session = ThinkingPromptSession(
        app_info=app_info,
        message=">>> ",
        max_thinking_height=8,
    )

    @session.on_input
    async def handle(text: str):
        """Simulate a task with progress updates."""
        if not text.strip():
            return

        # Mutable state that the callback reads
        progress = {"percent": 0, "status": "Starting..."}

        def get_content():
            """Return current content - called repeatedly by the UI."""
            bar_width = 30
            filled = int(bar_width * progress["percent"] / 100)
            bar = "█" * filled + "░" * (bar_width - filled)

            return (
                f"Processing: {text[:40]}{'...' if len(text) > 40 else ''}\n"
                f"Progress: [{bar}] {progress['percent']}%\n"
                f"\n"
                f"Status: {progress['status']}\n"
            )

        # Start thinking mode
        session.start_thinking(get_content)

        # Simulate work with progress updates
        steps = [
            (10, "Initializing..."),
            (25, "Loading resources..."),
            (40, "Processing data..."),
            (55, "Analyzing patterns..."),
            (70, "Computing results..."),
            (85, "Finalizing..."),
            (95, "Almost done..."),
            (100, "Complete!"),
        ]

        for percent, status in steps:
            progress["percent"] = percent
            progress["status"] = status
            await asyncio.sleep(0.4)

        await asyncio.sleep(0.3)

        # Finish thinking - content is added to chat history
        session.finish_thinking()

        # Add response to chat history
        session.add_response(f"Processed: {text}")

    await session.run_async()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
