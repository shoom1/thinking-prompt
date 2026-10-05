"""
Inline dialogs: dialogs drawn as rows under the prompt instead of boxes.

Run with: conda run -n thinking_prompt python examples/inline_dialogs.py
Commands: yesno, choice, dropdown, checklist, settings, box, quit
"""
import asyncio

from thinking_prompt import (
    AppInfo,
    CheckboxItem,
    ChecklistItem,
    DropdownItem,
    RadioItem,
    TextItem,
    ThinkingPromptSession,
)


async def main() -> None:
    session = ThinkingPromptSession(
        app_info=AppInfo(
            name="Inline dialogs",
            version="0.4",
            welcome_message="Commands: yesno, choice, dropdown, checklist, settings, box, quit",
        ),
        dialog_placement="inline",
    )

    @session.on_input
    async def handle(text: str) -> None:
        command = text.strip().lower()
        if command == "quit":
            session.exit()
        elif command == "yesno":
            ok = await session.yes_no_dialog("Delete 3 files?", "This can't be undone.")
            session.add_response(f"yes_no_dialog -> {ok}")
        elif command == "choice":
            action = await session.choice_dialog("Unsaved changes", "", ["Save", "Discard", "Cancel"])
            session.add_response(f"choice_dialog -> {action}")
        elif command == "dropdown":
            theme = await session.dropdown_dialog(
                "Theme", "Pick a theme:", ["dark", "light", "mono", "terminal"], default="light"
            )
            session.add_response(f"dropdown_dialog -> {theme}")
        elif command == "checklist":
            tools = await session.checklist_dialog(
                "Tools", "Enable any:", ["search", "code execution", "file access"],
                defaults=["search"],
            )
            session.add_response(f"checklist_dialog -> {tools}")
        elif command == "settings":
            result = await session.show_settings_dialog("Settings", [
                DropdownItem(key="model", label="Model", options=["small", "medium", "large"],
                             default="medium"),
                CheckboxItem(key="stream", label="Stream output", default=True),
                TextItem(key="name", label="Name", default=""),
                ChecklistItem(key="tools", label="Tools", options=["search", "code"],
                              default=("search",)),
                RadioItem(key="mode", label="Mode", options=["fast", "careful"], default="fast"),
            ])
            session.add_response(f"show_settings_dialog -> {result}")
        elif command == "box":
            ok = await session.yes_no_dialog("Same question", "...as a box.", placement="box")
            session.add_response(f"yes_no_dialog (box) -> {ok}")
        elif command:
            session.add_warning(f"Unknown command: {command}")

    await session.run_async()


if __name__ == "__main__":
    asyncio.run(main())
