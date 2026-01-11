"""
Application info for ThinkingPromptSession.

Provides AppInfo dataclass for app metadata and welcome message.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional, Tuple, Union

from prompt_toolkit.formatted_text import FormattedText


@dataclass
class AppInfo:
    """
    Application information displayed at startup.

    Provides app metadata and optional welcome message that is printed
    when the session starts.

    Example:
        # Simple usage - auto-generates welcome box
        app_info = AppInfo(name="MyApp", version="1.0.0")

        # With custom welcome message string
        app_info = AppInfo(
            name="MyApp",
            version="1.0.0",
            welcome_message="Welcome to MyApp!\\nType 'help' for commands.",
        )

        # With callable for dynamic content
        app_info = AppInfo(
            name="MyApp",
            version="1.0.0",
            welcome_message=lambda: f"Welcome! Today is {date.today()}",
        )

        # With Rich formatting (requires rich package)
        from rich.panel import Panel
        from rich.markdown import Markdown

        app_info = AppInfo(
            name="MyApp",
            version="1.0.0",
            welcome_message=lambda: Panel("Welcome!", title="MyApp v1.0.0"),
        )

        # Or with Markdown
        app_info = AppInfo(
            name="MyApp",
            version="1.0.0",
            welcome_message=lambda: Markdown("# MyApp\\n\\n**Welcome!**"),
        )

        # Custom key bindings
        app_info = AppInfo(
            name="MyApp",
            version="1.0.0",
            fullscreen_key="c-f",  # Ctrl+F for fullscreen
            expand_key="c-x",      # Ctrl+X for expand/collapse
        )

        # Enable fullscreen mode (disabled by default)
        app_info = AppInfo(
            name="MyApp",
            version="1.0.0",
            fullscreen_enabled=True,
        )

        # Custom thinking animation
        app_info = AppInfo(
            name="MyApp",
            version="1.0.0",
            thinking_text="Processing",
            thinking_animation=(".  ", ".. ", "..."),
            thinking_animation_position="after",
        )

        session = ThinkingPromptSession(app_info=app_info)
    """

    name: str
    version: Optional[str] = None
    welcome_message: Union[str, Callable[[], Any], None] = None

    # Key bindings (prompt_toolkit format, e.g., "c-e" for Ctrl+E)
    fullscreen_key: str = "c-e"
    """Key binding to toggle fullscreen mode. Default: Ctrl+E"""

    expand_key: str = "c-t"
    """Key binding to expand/collapse thinking box (prompt mode only). Default: Ctrl+T"""

    # Feature flags
    fullscreen_enabled: bool = False
    """Enable fullscreen mode toggle. When False (default), only thinking box
    expand/collapse in prompt mode is available. Ctrl+E has no effect."""

    # Thinking animation settings
    thinking_text: str = "Thinking"
    """Text shown in the thinking separator. Set to empty string for no text."""

    thinking_animation: Tuple[str, ...] = field(
        default=("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    )
    """Animation frames for the thinking indicator. Set to empty tuple for no animation."""

    thinking_animation_position: Literal["before", "after"] = "before"
    """Position of animation relative to text: 'before' (default) or 'after'."""

    echo_thinking: bool = True
    """Whether to print thinking content to console after completion. Default: True."""

    def get_welcome_content(self) -> Any:
        """
        Get the welcome content to display at startup.

        If welcome_message is set, uses that (calling it if callable).
        Otherwise, generates a simple box with name and version.

        Returns:
            The welcome content - can be a string or a Rich renderable.
        """
        if self.welcome_message is not None:
            if callable(self.welcome_message):
                return self.welcome_message()
            return self.welcome_message

        # Generate default welcome box
        return self._format_default_welcome()

    def _format_default_welcome(self) -> str:
        """
        Format the default welcome box.

        Returns:
            A box with app name and version.
        """
        version_str = f" v{self.version}" if self.version else ""
        title = f"{self.name}{version_str}"
        width = max(len(title) + 4, 30)

        border = "─" * width
        padding = " " * ((width - len(title)) // 2)
        # Handle odd widths
        padding_right = " " * (width - len(title) - len(padding))

        return f"┌{border}┐\n│{padding}{title}{padding_right}│\n└{border}┘"
