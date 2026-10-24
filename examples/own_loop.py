#!/usr/bin/env python3
"""
Your own input loop: async with session runs the app, prompt_async() reads
each input, query() runs it as the query Ctrl+C cancels.

Type while a reply is running: the line waits under the prompt and runs
next (input_while_busy="queue"); Up on an empty prompt takes it back.
"/bg TEXT" runs a reply as a background task beside the next input.
Ctrl+C cancels the running reply, Ctrl+D exits.
"""
import asyncio

from thinking_prompt import AppInfo, ThinkingPromptSession


async def main() -> None:
    session = ThinkingPromptSession(
        app_info=AppInfo(name="Own loop", welcome_message="Type anything; /bg TEXT runs beside."),
        input_while_busy="queue",
    )
    jobs: set[asyncio.Task[None]] = set()
    count = 0

    async def reply(text: str) -> None:
        async with session.thinking(title=f"Replying to {text!r}") as box:
            for step in range(1, 6):
                box.append(f"step {step}/5\n")
                await asyncio.sleep(0.6)
        session.add_response(f"Done: {text}")

    async with session:
        while True:
            try:
                text = await session.prompt_async()
            except (EOFError, KeyboardInterrupt):
                break
            count += 1
            if text.startswith("/bg "):
                job = asyncio.create_task(reply(text[4:]))
                jobs.add(job)
                job.add_done_callback(jobs.discard)
            elif text.strip():
                await session.query(reply(text))
        for job in jobs:
            job.cancel()
    print(f"{count} inputs.")


if __name__ == "__main__":
    asyncio.run(main())
