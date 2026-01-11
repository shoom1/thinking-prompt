"""
Demo: session.clear() functionality

Shows how to clear the terminal and reset to startup state.
Type 'clear' to reset the display, 'exit' to quit.
"""
from thinking_prompt import ThinkingPromptSession, AppInfo
import asyncio

app_info = AppInfo(name="ClearDemo", version="1.0")
session = ThinkingPromptSession(app_info=app_info)


@session.on_input
async def handle(text):
    if text == "clear":
        session.clear()
    elif text == "exit":
        session.exit()
    else:
        session.add_response(f"Echo: {text}")


if __name__ == "__main__":
    asyncio.run(session.run_async())
