#!/usr/bin/env python3
"""
Chat-like demo of ThinkingPromptSession.

This example demonstrates:
- Welcome message display at startup
- Decorator-style handler registration
- Thinking box appearing above the prompt during processing
- Real-time streaming updates in the thinking box
- Expand/collapse thinking box with Ctrl+T

Run:
    python examples/chat_demo.py
"""
import asyncio

from thinking_prompt import ThinkingPromptSession, AppInfo


async def main():
    app_info = AppInfo(name="ChatDemo", version="1.0.0")
    session = ThinkingPromptSession(
        app_info=app_info,
        message="You: ",
        max_thinking_height=5,
        status_text="Ctrl+C: cancel | Ctrl+D: exit",
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

        # Phase 1: Initial analysis
        chunks.append("Analyzing your input...\n")
        await asyncio.sleep(0.4)

        # Phase 2: Show what we're processing
        chunks.append(f"Received: \"{user_input}\"\n")
        await asyncio.sleep(0.3)

        # Phase 3: Simulated reasoning steps (more than max_thinking_height to show truncation)
        steps = [
            "Step 1: Parsing input...",
            "Step 2: Tokenizing text...",
            "Step 3: Analyzing semantics...",
            "Step 4: Processing concepts...",
            "Step 5: Building context...",
            "Step 6: Generating candidates...",
            "Step 7: Ranking responses...",
            "Step 8: Selecting best response...",
        ]

        for step in steps:
            chunks.append(f"  {step}\n")
            await asyncio.sleep(0.3)

        # Phase 4: Done
        chunks.append("\nDone.\n")
        await asyncio.sleep(0.3)

        # Finish thinking - adds thinking content to history
        session.finish_thinking()

        # Add the actual response (separate from thinking)
        response = f"I understood your message: '{user_input[:50]}{'...' if len(user_input) > 50 else ''}'"
        session.add_response(response)

    # Run the session - handler already registered with @on_input
    await session.run_async()


if __name__ == "__main__":
    asyncio.run(main())
