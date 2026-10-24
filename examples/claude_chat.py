#!/usr/bin/env python3
"""
Chat with Claude: its thinking streams into a thinking box, and its answer
prints as markdown once it's done.

Needs the Anthropic SDK and an API key in ANTHROPIC_API_KEY. To keep the
key out of your shell history, put ANTHROPIC_API_KEY=... in a .env file
(one git ignores) and run the example with python-dotenv:

    pip install anthropic "thinking-prompt[all]" "python-dotenv[cli]"
    dotenv run -- python examples/claude_chat.py

A message typed while Claude answers waits under the prompt and goes next
(Up takes it back). Ctrl+T shows all of the thinking, Ctrl+C cancels a
reply, Ctrl+D exits.
"""
import asyncio

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam

from thinking_prompt import AppInfo, ThinkingPromptSession

MODEL = "claude-sonnet-5-5"


async def main() -> None:
    client = AsyncAnthropic()  # reads ANTHROPIC_API_KEY
    history: list[MessageParam] = []
    session = ThinkingPromptSession(
        app_info=AppInfo(
            name="Claude chat",
            welcome_message=f"Chatting with {MODEL}. Ctrl+D exits.",
        ),
        message="> ",
        input_while_busy="queue",
    )

    @session.on_input
    async def handle(text: str) -> None:
        if not text.strip():
            return
        turn: MessageParam = {"role": "user", "content": text}
        async with session.thinking(title="Thinking") as box:
            async with client.messages.stream(
                model=MODEL,
                max_tokens=16000,
                # "summarized": stream the thinking's text, which some models
                # leave out by default.
                thinking={"type": "adaptive", "display": "summarized"},
                messages=[*history, turn],
            ) as stream:
                async for event in stream:
                    if event.type == "thinking":
                        box.append(event.thinking)
                    elif event.type == "text" and box.title != "Answering":
                        box.set_title("Answering")
                reply = await stream.get_final_message()
        # A cancelled reply (Ctrl+C) never gets here, so it stays out of the
        # history. The thinking blocks go back with the turn, as the API asks.
        history.extend([turn, {"role": "assistant", "content": reply.content}])
        answer = "".join(block.text for block in reply.content if block.type == "text")
        session.add_response(answer, markdown=True)

    await session.run_async()


if __name__ == "__main__":
    asyncio.run(main())
