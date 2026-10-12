"""
Application info for ThinkingPromptSession.

Provides AppInfo dataclass for app metadata and welcome message.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class AppInfo:
    """
    The banner printed when the session starts: the app's name and version,
    or your own welcome message. Without an AppInfo there is no banner.

    Behavior (full screen, keys, the thinking header) is set on
    ThinkingPromptSession itself.

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

        session = ThinkingPromptSession(app_info=app_info)
    """

    name: str
    version: str | None = None
    welcome_message: str | Callable[[], Any] | None = None

    def get_welcome_content(self) -> Any:
        """
        Get the welcome content to display at startup.

        If welcome_message is set, uses that (calling it if callable).
        Otherwise, generates a simple box with name and version.

        Returns:
            The welcome content - can be a string or a Rich renderable.
            Nothing is printed for "" (or a callable returning "" or None).
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
