#!/usr/bin/env python3
"""
Demo: themes and runtime theme switching.

Commands:
    /theme <name>     Switch theme (dark, light, mono, terminal, auto)
    /theme <name> !   Switch and repaint the whole transcript
    /themes           List themes
    anything else     Echo with a small thinking phase

Run:
    python examples/demo_themes.py
    NO_COLOR=1 python examples/demo_themes.py   # forced colorless
"""
import asyncio

from thinking_prompt import AppInfo, ThinkingPromptSession

THEME_NAMES = ("dark", "light", "mono", "terminal", "auto")


async def main() -> None:
    session = ThinkingPromptSession(
        app_info=AppInfo(name="ThemesDemo", version="1.0"),
        theme="auto",
        message=">>> ",
    )

    @session.on_input
    async def handle(text: str) -> None:
        text = text.strip()
        if not text:
            return
        if text == "/themes":
            session.add_response("Themes: " + ", ".join(THEME_NAMES))
            return
        if text.startswith("/theme"):
            parts = text.split()
            if len(parts) < 2:
                session.add_warning("Usage: /theme <name> [!]")
                return
            repaint = parts[-1] == "!"
            name = parts[1]
            try:
                session.set_theme(name, repaint=repaint)
            except ValueError as e:
                session.add_error(str(e))
                return
            session.add_success(f"Theme: {name}" + (" (repainted)" if repaint else ""))
            return

        async with session.thinking(title="Working") as ctx:
            ctx.append("Analyzing input...\n")
            await asyncio.sleep(0.4)
            ctx.append("Done.\n")
        session.add_response(f"# Echo\n\n`{text}`", markdown=True)

    await session.run_async()


if __name__ == "__main__":
    asyncio.run(main())
