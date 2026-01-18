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

    # Dialog styles (dark theme to match terminal)
    dialog: str = "bg:#2a2a2a"  # Dark grey background
    dialog_title: str = "fg:#ffffff bold"  # White bold title
    dialog_body: str = "bg:#2a2a2a fg:#e0e0e0"  # Dark bg, light text
    dialog_border: str = "fg:#888888"  # Grey border
    dialog_shadow: str = "bg:#000000"  # Black shadow/background
    dialog_button: str = "bg:#404040 fg:#e0e0e0"  # Dark button
    dialog_button_focused: str = "bg:#0066cc fg:#ffffff bold"  # Blue focused

    # Form control styles (for settings dialog)
    radio_list: str = "bg:#2a2a2a fg:#e0e0e0"  # Dark background
    radio_selected: str = "fg:#88c0d0 bold"  # Cyan selected item
    checkbox_list: str = "bg:#2a2a2a fg:#e0e0e0"  # Dark background
    checkbox_selected: str = "fg:#88c0d0 bold"  # Cyan selected
    text_area: str = "bg:#3a3a3a fg:#ffffff"  # Slightly lighter input bg
    select_value: str = "fg:#88c0d0"  # Cyan for selected value
    select_arrow: str = "fg:#888888"  # Grey arrow indicator
    checkbox_mark: str = "fg:#88c0d0"  # Cyan for checkbox mark

    # Settings list styles (clean list with focus indicator)
    setting_indicator: str = "fg:#88c0d0"  # Cyan focus indicator (›)
    setting_label: str = "fg:#e0e0e0"  # Light grey label
    setting_label_selected: str = "fg:#88c0d0"  # Cyan when selected
    setting_value: str = "fg:#888888"  # Grey value
    setting_value_selected: str = "fg:#88c0d0 italic"  # Cyan italic when selected
    setting_value_true: str = "fg:#a3be8c"  # Green for true
    setting_value_true_selected: str = "fg:#a3be8c italic"  # Green italic
    setting_value_false: str = "fg:#888888"  # Grey for false
    setting_value_false_selected: str = "fg:#888888 italic"  # Grey italic
    setting_desc: str = "fg:#666666"  # Dimmed description
    setting_desc_selected: str = "fg:#888888"  # Slightly brighter when selected

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
            # Dialog styles
            'dialog': self.dialog,
            'dialog.body': self.dialog_body,
            'dialog frame.label': self.dialog_title,
            'dialog frame.border': self.dialog_border,
            'dialog shadow': self.dialog_shadow,
            'button': self.dialog_button,
            'button.focused': self.dialog_button_focused,
            # Form controls
            'radio-list': self.radio_list,
            'radio-selected': self.radio_selected,
            'checkbox-list': self.checkbox_list,
            'checkbox-selected': self.checkbox_selected,
            'text-area': self.text_area,
            'select-value': self.select_value,
            'select-arrow': self.select_arrow,
            'checkbox-mark': self.checkbox_mark,
            # Settings list
            'setting-indicator': self.setting_indicator,
            'setting-label': self.setting_label,
            'setting-label-selected': self.setting_label_selected,
            'setting-value': self.setting_value,
            'setting-value-selected': self.setting_value_selected,
            'setting-value-true': self.setting_value_true,
            'setting-value-true-selected': self.setting_value_true_selected,
            'setting-value-false': self.setting_value_false,
            'setting-value-false-selected': self.setting_value_false_selected,
            'setting-desc': self.setting_desc,
            'setting-desc-selected': self.setting_desc_selected,
        })


# Default styles instance
DEFAULT_STYLES = ThinkingPromptStyles()
