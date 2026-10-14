"""
A settings dialog built from a Dialog and its fields.

Run with: conda run -n thinking_prompt python examples/settings_dialog_demo.py
Type 'settings' (a box) or 'inline', anything else to see the settings,
'quit' to exit.
"""
import asyncio

from thinking_prompt import (
    AppInfo,
    ButtonConfig,
    CheckboxField,
    ChecklistField,
    Dialog,
    DropdownField,
    RadioField,
    SelectField,
    TextField,
    ThinkingPromptSession,
)

# Keys whose values must never be echoed verbatim in demo output.
SECRET_KEYS = {"api_key"}


def settings_dialog(settings: dict, placement: str) -> Dialog:
    """A form over ``settings``: Save returns every value, Cancel None."""
    dialog = Dialog(
        "Settings",
        fields=[
            DropdownField(
                "model", "Model", description="The model that answers",
                options=["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"], default=settings["model"],
            ),
            SelectField("size", "Text size", options=["small", "medium", "large"], default=settings["size"]),
            CheckboxField(
                "stream", "Stream output", description="Show answers as they arrive",
                default=settings["stream"],
            ),
            TextField("api_key", "API key", default=settings["api_key"], password=True),
            ChecklistField("tools", "Tools", options=["search", "code", "files"], default=tuple(settings["tools"])),
            RadioField("style", "Answers", options=["concise", "detailed"], default=settings["style"]),
        ],
        width=60,
        placement=placement,
    )
    dialog.buttons = [
        ButtonConfig("Save", handler=lambda: dialog.set_result(dialog.values)),
        ButtonConfig("Cancel"),
    ]
    return dialog


def masked(values: dict) -> dict:
    return {k: ("***" if k in SECRET_KEYS and v else v) for k, v in values.items()}


async def main():
    session = ThinkingPromptSession(app_info=AppInfo(
        name="Settings Demo",
        version="1.0.0",
        welcome_message="Type 'settings' (a box) or 'inline', 'quit' to exit.",
    ))
    settings = {
        "model": "gpt-4",
        "size": "medium",
        "stream": True,
        "api_key": "",
        "tools": ["search"],
        "style": "concise",
    }

    @session.on_input
    async def handle(text: str):
        command = text.strip().lower()
        if command == "quit":
            session.exit()
        elif command in ("settings", "inline"):
            placement = "inline" if command == "inline" else "box"
            values = await session.show_dialog(settings_dialog(settings, placement))
            if values is None:
                session.add_response("Settings cancelled.")
                return
            changed = {k: v for k, v in values.items() if v != settings[k]}
            settings.update(values)
            session.add_response(f"Changed: {masked(changed)}" if changed else "No changes made.")
        else:
            session.add_response(f"Current settings: {masked(settings)}")

    await session.run_async()


if __name__ == "__main__":
    asyncio.run(main())
