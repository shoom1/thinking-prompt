#!/usr/bin/env python3
"""
Streaming example demonstrating real-time thinking box updates.

This simulates an LLM-style character-by-character streaming response.

Run:
    python examples/streaming.py
"""
import asyncio
import random

from thinking_prompt import ThinkingPromptSession, AppInfo


# Sample responses for simulation
SAMPLE_RESPONSES = [
    "The answer to your question involves several key considerations. First, we need to understand the underlying principles at play. Second, we should examine the specific context of your situation. Finally, we can draw conclusions based on this analysis.",
    "Let me think about this step by step. The core issue seems to be related to how different components interact. By breaking this down into smaller parts, we can better understand the relationship between cause and effect.",
    "This is an interesting problem! There are multiple approaches we could take here. One option is to focus on efficiency, while another prioritizes clarity. The best choice depends on your specific requirements and constraints.",
]


async def main():
    """Main async function."""
    app_info = AppInfo(name="StreamingDemo", version="1.0.0")
    session = ThinkingPromptSession(
        app_info=app_info,
        message="Question: ",
        max_thinking_height=15,
    )

    @session.on_input
    async def handle(question: str):
        """Simulate an LLM streaming response with thinking box."""
        if not question.strip():
            return

        # Pick a random response
        response = random.choice(SAMPLE_RESPONSES)

        # Use a list for O(1) append
        chunks = []

        def get_content():
            return ''.join(chunks)

        # Start thinking mode
        session.start_thinking(get_content)

        # Start with a header
        chunks.append(f"Thinking about: {question[:50]}...\n\n")
        await asyncio.sleep(0.2)

        # Stream character by character (like an LLM)
        for char in response:
            chunks.append(char)
            # Variable delay for more realistic effect
            delay = 0.02 if char in " \n" else 0.01
            await asyncio.sleep(delay)

        # Add a newline at the end
        chunks.append("\n")
        await asyncio.sleep(0.3)

        # Finish and persist to console
        session.finish_thinking()

        # Add to chat history
        session.add_response(response)

    # Run the session
    await session.run_async()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
