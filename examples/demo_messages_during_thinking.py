#!/usr/bin/env python3
"""
Demo: Output messages during a thinking session.

This demo shows how to output status messages, warnings, markdown,
and other content to the console while the thinking box is active.
Messages appear above the prompt and thinking box.

Run:
    python examples/demo_messages_during_thinking.py
"""
import asyncio

from thinking_prompt import ThinkingPromptSession, AppInfo


async def main():
    app_info = AppInfo(
        name="MessagesDemo",
        version="1.0.0",
        fullscreen_enabled=False,  # Keep in prompt mode to see messages
    )

    session = ThinkingPromptSession(
        app_info=app_info,
        message=">>> ",
        max_thinking_height=8,
    )

    @session.on_input
    async def handle(user_input: str):
        """Process user input, outputting status messages during thinking."""
        if not user_input.strip():
            return

        # Use the context manager for clean thinking management
        async with session.thinking() as content:
            # Initial thinking content
            content.append("Starting analysis...\n")
            await asyncio.sleep(0.5)

            # Output a system message - appears above the thinking box
            session.add_message("system", "Connecting to backend service...")
            await asyncio.sleep(0.3)

            content.append("Phase 1: Parsing input\n")
            await asyncio.sleep(0.4)

            # Output a success message
            session.add_success("Backend connection established")
            await asyncio.sleep(0.3)

            content.append("Phase 2: Processing data\n")
            await asyncio.sleep(0.5)

            # Output markdown content during thinking
            session.add_response(
                "## Processing Details\n"
                "- Input length: **{} chars**\n"
                "- Mode: `standard`\n".format(len(user_input)),
                markdown=True
            )
            await asyncio.sleep(0.4)

            # Simulate a warning condition
            if len(user_input) > 50:
                session.add_warning("Input exceeds recommended length")
                content.append("  (using truncated analysis)\n")
            await asyncio.sleep(0.3)

            content.append("Phase 3: Generating response\n")
            await asyncio.sleep(0.4)

            # Show progress with multiple messages
            for i in range(1, 4):
                session.add_message("system", f"Processing chunk {i}/3...")
                content.append(f"  Chunk {i} processed\n")
                await asyncio.sleep(0.3)

            # Output code block during thinking
            session.add_code(
                f'result = analyze("{user_input[:20]}...")\nprint(result)',
                language="python"
            )
            await asyncio.sleep(0.3)

            content.append("\nAnalysis complete!\n")
            await asyncio.sleep(0.2)

        # After thinking finishes, add the final response with markdown
        session.add_success("All operations completed successfully")

        # Final markdown response
        session.add_response(
            "### Result\n\n"
            f"> {user_input[:60]}{'...' if len(user_input) > 60 else ''}\n\n"
            "**Status:** Complete\n\n"
            "---\n"
            "*Thank you for using MessagesDemo!*",
            markdown=True
        )

    # Run the session
    await session.run_async()


if __name__ == "__main__":
    print("Type messages and watch status updates appear during thinking.")
    print("Includes markdown formatting, code blocks, and status messages.")
    print("Try both short and long (>50 char) messages to see warning behavior.")
    print("Press Ctrl+C or Ctrl+D to exit.\n")
    asyncio.run(main())
