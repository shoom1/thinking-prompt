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

    Base theme colors control the overall appearance:
    - Customize `menu_*` styles to change both dropdown and completion menus
    - Customize `color_*` properties to change colors throughout

    Example:
        styles = ThinkingPromptStyles(
            color_accent="#ff6600",  # Orange accent instead of cyan
            menu_selected="bg:#ff6600 fg:#ffffff",  # Orange selection
        )
        session = ThinkingPromptSession(styles=styles)
    """

    # ==========================================================================
    # Base theme colors - customize these to change colors throughout
    # ==========================================================================
    color_accent: str = "#88c0d0"  # Cyan - primary accent (selection, indicators)
    color_accent_button: str = "#0066cc"  # Blue - button/menu selection highlight
    color_success: str = "#a3be8c"  # Green - success states
    color_warning: str = "#ebcb8b"  # Amber - warnings, system messages
    color_error: str = "#bf616a"  # Red - errors
    color_text: str = "#e0e0e0"  # Light grey - primary text
    color_text_bright: str = "#ffffff"  # White - emphasized text
    color_text_muted: str = "#888888"  # Grey - secondary/muted text
    color_text_dim: str = "#666666"  # Dark grey - very dim text
    color_bg_dark: str = "#333333"  # Dark - menus, dropdowns
    color_bg_dialog: str = "#2a2a2a"  # Darker - dialog background
    color_bg_input: str = "#3a3a3a"  # Medium - input fields, highlights

    # ==========================================================================
    # Shared menu styles - used by both dropdown and completion menus
    # ==========================================================================
    menu_bg: str = ""  # Defaults to color_bg_dark
    menu_item: str = ""  # Defaults to color_text on color_bg_dark
    menu_item_selected: str = ""  # Defaults to color_text_bright on color_accent_button
    menu_border: str = ""  # Defaults to color_text_muted on color_bg_dark
    menu_meta: str = ""  # Defaults to color_text_muted on color_bg_dark
    menu_meta_selected: str = ""  # Defaults to slightly dimmed on color_accent_button

    # ==========================================================================
    # Thinking box styles
    # ==========================================================================
    thinking_box: str = "fg:#a0a0a0 italic"
    thinking_box_border: str = "fg:#606060"
    thinking_box_hint: str = "fg:#707070 italic"

    # ==========================================================================
    # Status bar
    # ==========================================================================
    status_bar: str = "bg:#202040 fg:#808090"

    # ==========================================================================
    # Chat history
    # ==========================================================================
    history: str = ""
    user_prefix: str = ""  # Defaults to color_accent on color_bg_input
    user_message: str = ""  # Defaults to color_text_bright on color_bg_input italic
    user_separator: str = ""  # Defaults to color_text_muted
    assistant_prefix: str = "fg:cyan bold"
    assistant_message: str = ""  # Defaults to color_text_bright
    thinking_message: str = "fg:#a0a0a0 italic"
    system_message: str = ""  # Defaults to color_warning

    # ==========================================================================
    # Status messages
    # ==========================================================================
    error_message: str = ""  # Defaults to color_error bold
    warning_message: str = ""  # Defaults to color_warning
    success_message: str = ""  # Defaults to color_success

    # ==========================================================================
    # Input prompt
    # ==========================================================================
    prompt: str = ""
    input_separator: str = "fg:#444444"

    # ==========================================================================
    # Dialog styles
    # ==========================================================================
    dialog: str = ""  # Defaults to bg:color_bg_dialog
    dialog_title: str = ""  # Defaults to color_text_bright bold
    dialog_body: str = ""  # Defaults to color_text on color_bg_dialog
    dialog_border: str = ""  # Defaults to color_text_muted
    dialog_shadow: str = "bg:#000000"
    dialog_button: str = ""  # Defaults to color_text on #404040
    dialog_button_focused: str = ""  # Defaults to color_text_bright on color_accent_button bold

    # ==========================================================================
    # Form controls
    # ==========================================================================
    radio_list: str = ""  # Defaults to color_text on color_bg_dialog
    radio_selected: str = ""  # Defaults to color_accent bold
    checkbox_list: str = ""  # Defaults to color_text on color_bg_dialog
    checkbox_selected: str = ""  # Defaults to color_accent bold
    text_area: str = ""  # Defaults to color_text_bright on color_bg_input
    select_value: str = ""  # Defaults to color_accent
    select_arrow: str = ""  # Defaults to color_text_muted
    checkbox_mark: str = ""  # Defaults to color_accent

    # ==========================================================================
    # Settings list
    # ==========================================================================
    setting_indicator: str = ""  # Defaults to color_accent
    setting_label: str = ""  # Defaults to color_text
    setting_label_selected: str = ""  # Defaults to color_accent
    setting_value: str = ""  # Defaults to color_text_muted
    setting_value_selected: str = ""  # Defaults to color_accent italic
    setting_value_true: str = ""  # Defaults to color_success
    setting_value_true_selected: str = ""  # Defaults to color_success italic
    setting_value_false: str = ""  # Defaults to color_text_muted
    setting_value_false_selected: str = ""  # Defaults to color_text_muted italic
    setting_desc: str = ""  # Defaults to color_text_dim
    setting_desc_selected: str = ""  # Defaults to color_text_muted

    # ==========================================================================
    # Scrollbar
    # ==========================================================================
    scrollbar_background: str = ""  # Defaults to color_bg_dark
    scrollbar_button: str = ""  # Defaults to color_text_dim

    # ==========================================================================
    # Markdown styles (for Rich rendering)
    # ==========================================================================
    markdown_h1: str = "bold"
    markdown_h1_border: str = "dim"  # Underline below H1
    markdown_h2: str = "bold"
    markdown_h3: str = "bold"
    markdown_h4: str = "bold"
    markdown_h5: str = "bold"
    markdown_h6: str = "bold"
    markdown_code: str = "bold"
    markdown_code_block: str = ""
    markdown_item_bullet: str = "bold"
    markdown_item_number: str = "bold"
    markdown_link: str = ""
    markdown_link_url: str = "underline"
    markdown_hr: str = "dim"
    markdown_block_quote: str = "italic"

    def __post_init__(self) -> None:
        """Apply default values based on base theme colors."""
        # Menu styles
        if not self.menu_bg:
            self.menu_bg = f"bg:{self.color_bg_dark}"
        if not self.menu_item:
            self.menu_item = f"fg:{self.color_text} bg:{self.color_bg_dark}"
        if not self.menu_item_selected:
            self.menu_item_selected = f"fg:{self.color_accent} bg:#454545 noreverse"
        if not self.menu_border:
            self.menu_border = f"fg:{self.color_text_muted} bg:{self.color_bg_dark}"
        if not self.menu_meta:
            self.menu_meta = f"fg:{self.color_text} bg:{self.color_bg_dark}"
        if not self.menu_meta_selected:
            self.menu_meta_selected = f"fg:{self.color_accent} bg:#454545 noreverse"

        # Chat history
        if not self.user_prefix:
            self.user_prefix = f"fg:{self.color_accent} bg:{self.color_bg_input}"
        if not self.user_message:
            self.user_message = f"fg:{self.color_text_bright} bg:{self.color_bg_input} italic"
        if not self.user_separator:
            self.user_separator = f"fg:{self.color_text_muted}"
        if not self.assistant_message:
            self.assistant_message = f"fg:{self.color_text_bright}"
        if not self.system_message:
            self.system_message = f"fg:{self.color_warning}"

        # Status messages
        if not self.error_message:
            self.error_message = f"fg:{self.color_error} bold"
        if not self.warning_message:
            self.warning_message = f"fg:{self.color_warning}"
        if not self.success_message:
            self.success_message = f"fg:{self.color_success}"

        # Dialog
        if not self.dialog:
            self.dialog = f"bg:{self.color_bg_dialog}"
        if not self.dialog_title:
            self.dialog_title = f"fg:{self.color_text_bright} bold"
        if not self.dialog_body:
            self.dialog_body = f"bg:{self.color_bg_dialog} fg:{self.color_text}"
        if not self.dialog_border:
            self.dialog_border = f"fg:{self.color_text_muted}"
        if not self.dialog_button:
            self.dialog_button = f"bg:#404040 fg:{self.color_text}"
        if not self.dialog_button_focused:
            self.dialog_button_focused = f"bg:{self.color_accent_button} fg:{self.color_text_bright} bold"

        # Form controls
        if not self.radio_list:
            self.radio_list = f"bg:{self.color_bg_dialog} fg:{self.color_text}"
        if not self.radio_selected:
            self.radio_selected = f"fg:{self.color_accent} bold"
        if not self.checkbox_list:
            self.checkbox_list = f"bg:{self.color_bg_dialog} fg:{self.color_text}"
        if not self.checkbox_selected:
            self.checkbox_selected = f"fg:{self.color_accent} bold"
        if not self.text_area:
            self.text_area = f"bg:{self.color_bg_input} fg:{self.color_text_bright}"
        if not self.select_value:
            self.select_value = f"fg:{self.color_accent}"
        if not self.select_arrow:
            self.select_arrow = f"fg:{self.color_text_muted}"
        if not self.checkbox_mark:
            self.checkbox_mark = f"fg:{self.color_accent}"

        # Settings list
        if not self.setting_indicator:
            self.setting_indicator = f"fg:{self.color_accent}"
        if not self.setting_label:
            self.setting_label = f"fg:{self.color_text}"
        if not self.setting_label_selected:
            self.setting_label_selected = f"fg:{self.color_accent}"
        if not self.setting_value:
            self.setting_value = f"fg:{self.color_text_muted}"
        if not self.setting_value_selected:
            self.setting_value_selected = f"fg:{self.color_accent} italic"
        if not self.setting_value_true:
            self.setting_value_true = f"fg:{self.color_success}"
        if not self.setting_value_true_selected:
            self.setting_value_true_selected = f"fg:{self.color_success} italic"
        if not self.setting_value_false:
            self.setting_value_false = f"fg:{self.color_text_muted}"
        if not self.setting_value_false_selected:
            self.setting_value_false_selected = f"fg:{self.color_text_muted} italic"
        if not self.setting_desc:
            self.setting_desc = f"fg:{self.color_text_dim}"
        if not self.setting_desc_selected:
            self.setting_desc_selected = f"fg:{self.color_text_muted}"

        # Scrollbar
        if not self.scrollbar_background:
            self.scrollbar_background = f"bg:{self.color_bg_dark}"
        if not self.scrollbar_button:
            self.scrollbar_button = f"bg:{self.color_text_dim}"

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
            # Dropdown menu (uses shared menu styles)
            'setting-dropdown': self.menu_bg,
            'setting-dropdown-border': self.menu_border,
            'setting-dropdown-item': self.menu_item,
            'setting-dropdown-selected': self.menu_item_selected,
            # Completion menu (uses shared menu styles)
            'completion-menu': self.menu_bg,
            'completion-menu.completion': self.menu_item,
            'completion-menu.completion.current': self.menu_item_selected,
            'completion-menu.meta': self.menu_meta,
            'completion-menu.meta.current': self.menu_meta_selected,
            'completion-menu.meta.completion': self.menu_meta,
            'completion-menu.meta.completion.current': self.menu_meta_selected,
            'scrollbar.background': self.scrollbar_background,
            'scrollbar.button': self.scrollbar_button,
        })

    def to_rich_theme_dict(self) -> dict[str, str]:
        """
        Convert markdown styles to a Rich Theme dict.

        Returns:
            A dict suitable for rich.theme.Theme().
        """
        return {
            'markdown.h1': self.markdown_h1,
            'markdown.h1.border': self.markdown_h1_border,
            'markdown.h2': self.markdown_h2,
            'markdown.h3': self.markdown_h3,
            'markdown.h4': self.markdown_h4,
            'markdown.h5': self.markdown_h5,
            'markdown.h6': self.markdown_h6,
            'markdown.code': self.markdown_code,
            'markdown.code_block': self.markdown_code_block or 'none',
            'markdown.item.bullet': self.markdown_item_bullet,
            'markdown.item.number': self.markdown_item_number,
            'markdown.link': self.markdown_link or 'none',
            'markdown.link_url': self.markdown_link_url,
            'markdown.hr': self.markdown_hr,
            'markdown.block_quote': self.markdown_block_quote,
            'markdown.list': 'none',
            'markdown.paragraph': 'none',
            'markdown.text': 'none',
            'markdown.strong': 'bold',
            'markdown.em': 'italic',
            'markdown.emph': 'italic',
            'markdown.s': 'strike',
        }


# Default styles instance
DEFAULT_STYLES = ThinkingPromptStyles()
