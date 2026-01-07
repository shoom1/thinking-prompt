#!/usr/bin/env python3
"""
Interactive demo of ThinkingPromptSession.

This example simulates an AI assistant that "thinks" before responding.
The thinking box appears after you enter input, updates in real-time,
and then transitions to permanent console output.

Run:
    python examples/demo.py
"""
import asyncio

from thinking_prompt import ThinkingPromptSession, AppInfo


async def main():
    app_info = AppInfo(name="InteractiveDemo", version="1.0.0")
    session = ThinkingPromptSession(
        app_info=app_info,
        message="You: ",
        max_thinking_height=12,
    )

    @session.on_input
    async def handle(user_input: str):
        """Process user input with simulated thinking."""
        if not user_input.strip():
            return

        # Use a list for O(1) append
        chunks = []

        def get_content():
            return ''.join(chunks)

        # Start thinking mode
        session.start_thinking(get_content)

        # Update thinking box in real-time
        chunks.append("Analyzing your input...\n")
        await asyncio.sleep(0.4)

        chunks.append(f"Input received: \"{user_input}\"\n\n")
        await asyncio.sleep(0.3)

        # Simulated reasoning steps
        steps = [
            "Step 1: Parsing input structure...",
            "Step 2: Identifying key concepts...",
            "Step 3: Generating response...",
        ]

        for step in steps:
            chunks.append(f"{step}\n")
            await asyncio.sleep(0.5)

        # Stream the "response" character by character
        chunks.append("\nResponse: ")
        await asyncio.sleep(0.2)

        preview = user_input[:30] + ('...' if len(user_input) > 30 else '')
        response = f"I understood your message about '{preview}'"
        for char in response:
            chunks.append(char)
            await asyncio.sleep(0.03)

        chunks.append("\n")
        await asyncio.sleep(0.3)

        # Finish - content is printed to console (if not in fullscreen)
        session.finish_thinking()

        # Add response to chat history
        session.add_response(response)

    # Run the session with the registered handler
    await session.run_async()


if __name__ == "__main__":
    asyncio.run(main())
