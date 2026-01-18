"""
Demo of the SettingsDialog component.

Run with: conda run -n thinking_prompt python examples/settings_dialog_demo.py
"""
import asyncio
from thinking_prompt import (
    ThinkingPromptSession,
    AppInfo,
    DropdownItem,
    CheckboxItem,
    TextItem,
)


async def main():
    app_info = AppInfo(
        name="Settings Demo",
        version="1.0.0",
        welcome_message="Type 'settings' to open the settings dialog, 'quit' to exit.",
    )
    session = ThinkingPromptSession(app_info=app_info)

    # Current settings state
    current_settings = {
        "model": "gpt-4",
        "stream": True,
        "api_key": "",
    }

    @session.on_input
    async def handle(text: str):
        text = text.strip().lower()

        if text == "quit":
            session.exit()
            return

        if text == "settings":
            result = await session.show_settings_dialog(
                title="Settings",
                items=[
                    DropdownItem(
                        key="model",
                        label="Model",
                        description="Select the AI model to use",
                        options=["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"],
                        default=current_settings["model"],
                    ),
                    CheckboxItem(
                        key="stream",
                        label="Stream Output",
                        description="Enable streaming for real-time responses",
                        default=current_settings["stream"],
                    ),
                    TextItem(
                        key="api_key",
                        label="API Key",
                        description="Your OpenAI API key (stored securely)",
                        default=current_settings["api_key"],
                        password=True,
                    ),
                ],
            )

            if result is None:
                session.add_response("Settings cancelled.")
            elif not result:
                session.add_response("No changes made.")
            else:
                # Apply changes
                current_settings.update(result)
                session.add_response(f"Settings updated: {result}")
        else:
            session.add_response(f"Current settings: {current_settings}")

    await session.run_async()


if __name__ == "__main__":
    asyncio.run(main())
