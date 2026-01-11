"""
Styles for ThinkingPromptSession.

Provides ThinkingPromptStyles dataclass for clean style customization.
"""
from __future__ import annotations

from dataclasses import dataclass

from prompt_toolkit.styles import Style


@dataclass
class ThinkingPromptStyles:
    """
    Customizable styles for ThinkingPromptSession.

    All style strings use prompt_toolkit style format:
    - Colors: 'fg:#rrggbb' or 'bg:#rrggbb' or color names like 'red', 'blue'
    - Attributes: 'bold', 'italic', 'underline', 'reverse'
    - Combine with spaces: 'bg:#1a1a2e fg:#e0e0e0 italic'

    Example:
        styles = ThinkingPromptStyles(
            thinking_box="bg:#333333 #ffffff",
            status_bar="bg:blue white bold",
        )
        session = ThinkingPromptSession(styles=styles)
    """

    # Thinking box styles
    thinking_box: str = "fg:#a0a0a0 italic"  # Light grey italic
    thinking_box_border: str = "fg:#606060"
    thinking_box_hint: str = "fg:#707070 italic"

    # Status bar
    status_bar: str = "bg:#202040 fg:#808090"

    # Chat history (in fullscreen mode)
    history: str = ""  # Default terminal colors

    # Message styles (for chat history)
    user_prefix: str = "fg:#88c0d0 bg:#3a3a3a"  # Light blue on dark grey
    user_message: str = "fg:#ffffff bg:#3a3a3a italic"  # White italic on dark grey
    user_separator: str = "fg:#888888"  # Grey separator lines
    assistant_prefix: str = "fg:cyan bold"  # Cyan bold
    assistant_message: str = "fg:#ffffff"  # White
    thinking_message: str = "fg:#a0a0a0 italic"  # Light grey italic
    system_message: str = "fg:#ebcb8b"  # Amber/yellow - system notices

    # Status message styles
    error_message: str = "fg:#bf616a bold"  # Red bold
    warning_message: str = "fg:#ebcb8b"  # Amber/yellow
    success_message: str = "fg:#a3be8c"  # Green

    # Input prompt
    prompt: str = ""  # Default terminal colors
    input_separator: str = "fg:#444444"  # Grey separator around input

    def to_style(self) -> Style:
        """
        Convert to prompt_toolkit Style object.

        Returns:
            A Style object for use with prompt_toolkit Application.
        """
        return Style.from_dict({
            'thinking-box': self.thinking_box,
            'thinking-box.border': self.thinking_box_border,
            'thinking-box.hint': self.thinking_box_hint,
            'status': self.status_bar,
            'history': self.history,
            'history.user-prefix': self.user_prefix,
            'history.user-message': self.user_message,
            'history.user-separator': self.user_separator,
            'history.assistant-prefix': self.assistant_prefix,
            'history.assistant-message': self.assistant_message,
            'history.thinking': self.thinking_message,
            'history.system': self.system_message,
            'history.error': self.error_message,
            'history.warning': self.warning_message,
            'history.success': self.success_message,
            'prompt': self.prompt,
            'input-separator': self.input_separator,
        })


# Default styles instance
DEFAULT_STYLES = ThinkingPromptStyles()
