#!/usr/bin/env python3
"""
Basic example demonstrating the ThinkingPromptSession.

Run this script to see the thinking box in action:
    python examples/basic.py
"""
import asyncio

from thinking_prompt import ThinkingPromptSession, AppInfo


async def main():
    """Main async function demonstrating thinking box features."""
    app_info = AppInfo(name="BasicDemo", version="1.0.0")
    session = ThinkingPromptSession(
        app_info=app_info,
        message=">>> ",
        max_thinking_height=10,
    )

    @session.on_input
    async def handle(text: str):
        """Handle user input with simulated thinking."""
        if not text.strip():
            return

        # Use a list for O(1) append
        chunks = []

        def get_content():
            return ''.join(chunks)

        # Start thinking mode with content callback
        session.start_thinking(get_content)

        # Update thinking box with streaming content
        chunks.append("Processing your input...\n")
        await asyncio.sleep(0.3)

        # Simulate token-by-token processing
        words = text.split()
        for i, word in enumerate(words):
            chunks.append(f"  Token {i + 1}: {word}\n")
            await asyncio.sleep(0.15)

        chunks.append("\nAnalysis complete!\n")
        await asyncio.sleep(0.5)

        # Finish thinking - content moves to console
        session.finish_thinking()

        # Add response to chat history
        session.add_response(f"You entered {len(words)} word(s): {text}")

    # Run the session
    await session.run_async()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
