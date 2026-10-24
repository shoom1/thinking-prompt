"""
thinking_prompt - A prompt_toolkit extension with thinking box support.

This library provides a chat-like interface with a thinking box that appears
above the prompt during processing. The thinking box supports real-time
streaming updates and can be expanded to show all of its content.

Example:
    from thinking_prompt import ThinkingPromptSession, AppInfo
    import asyncio

    app_info = AppInfo(name="MyApp", version="1.0.0")
    session = ThinkingPromptSession(app_info=app_info)

    @session.on_input
    async def handle(text: str):
        if not text.strip():
            return

        async with session.thinking() as box:
            box.append("Processing...\\n")
            await asyncio.sleep(1)

        session.add_response(f"Echo: {text}")

    asyncio.run(session.run_async())

Key bindings (defaults; set expand_key on the session):
    Ctrl+T: Expand/collapse the thinking boxes
    Ctrl+C: Cancel the running handler; at an idle prompt, end the boxes
            nobody else will, or exit when no box is open
    Ctrl+D: Exit (on an empty input line)
"""

import logging

from .app_info import AppInfo
from .dialog import (
    ButtonConfig,
    Dialog,
)
from .fields import (
    CheckboxField,
    ChecklistField,
    ChoiceField,
    DropdownField,
    Field,
    RadioField,
    SelectField,
    TextField,
)
from .layout import ThinkingHeader
from .rich_utils import _renderable_to_ansi as rich_to_ansi
from .session import ThinkingPromptSession
from .spinner import Spinner
from .streaming import StreamingContent
from .styles import (
    DEFAULT_STYLES,
    ThinkingPromptStyles,
)
from .thinking_box import ThinkingBox
from .types import (
    ContentCallback,
    ContentFormat,
    InputHandler,
    Overflow,
    Placement,
)

__version__ = "0.4.1"

# Library logging convention: records go nowhere unless the application
# configures logging. Without a handler, Python's last-resort handler
# would print them to stderr — over the running UI.
logging.getLogger(__name__).addHandler(logging.NullHandler())

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
    "ThinkingBox",
    "ContentCallback",
    "ContentFormat",
    "Overflow",
    "Placement",
    "InputHandler",
    # Dialog
    "Dialog",
    "ButtonConfig",
    # Form fields
    "Field",
    "TextField",
    "CheckboxField",
    "SelectField",
    "DropdownField",
    "ChecklistField",
    "RadioField",
    "ChoiceField",
    # Layout
    "ThinkingHeader",
    "Spinner",
    # Utilities
    "rich_to_ansi",
]
