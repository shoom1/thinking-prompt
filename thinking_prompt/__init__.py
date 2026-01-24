"""
thinking_prompt - A prompt_toolkit extension with thinking box support.

This library provides a chat-like interface with a thinking box that appears
above the prompt during processing. The thinking box supports real-time
streaming updates and can be expanded to full-screen mode.

Example:
    from thinking_prompt import ThinkingPromptSession, AppInfo
    import asyncio

    app_info = AppInfo(name="MyApp", version="1.0.0")
    session = ThinkingPromptSession(app_info=app_info)

    @session.on_input
    async def handle(text: str):
        if not text.strip():
            return

        async with session.thinking() as content:
            content.append("Processing...\\n")
            await asyncio.sleep(1)

        session.add_response(f"Echo: {text}")

    asyncio.run(session.run_async())

Key bindings (defaults, configurable via AppInfo):
    Ctrl+T: Expand/collapse thinking box (in prompt mode)
    Ctrl+E: Toggle fullscreen mode (when fullscreen_enabled=True)
    Ctrl+C: Cancel current thinking or exit
    Ctrl+D: Exit application
"""

from .session import ThinkingPromptSession
from .app_info import AppInfo
from .styles import (
    ThinkingPromptStyles,
    DEFAULT_STYLES,
)
from .types import (
    StreamingContent,
    ContentCallback,
    MessageRole,
    InputHandler,
)
from .dialog import (
    DialogConfig,
    ButtonConfig,
    BaseDialog,
)
from .settings_dialog import (
    SettingsItem,
    DropdownItem,
    InlineSelectItem,
    CheckboxItem,
    TextItem,
    SettingsDialog,
)

__version__ = "0.2.3"

__all__ = [
    # Main class
    "ThinkingPromptSession",
    # App info
    "AppInfo",
    # Styles
    "ThinkingPromptStyles",
    "DEFAULT_STYLES",
    # Type helpers
    "StreamingContent",
    "ContentCallback",
    "MessageRole",
    "InputHandler",
    # Dialog
    "DialogConfig",
    "ButtonConfig",
    "BaseDialog",
    # Settings Dialog
    "SettingsItem",
    "DropdownItem",
    "InlineSelectItem",
    "CheckboxItem",
    "TextItem",
    "SettingsDialog",
]
