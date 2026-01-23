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

    # Dropdown menu styles
    setting_dropdown: str = "bg:#333333"  # Dark background for dropdown
    setting_dropdown_border: str = "fg:#888888 bg:#333333"  # Grey border on dark bg
    setting_dropdown_item: str = "fg:#e0e0e0 bg:#333333"  # Light text on dark
    setting_dropdown_selected: str = "fg:#ffffff bg:#0066cc"  # White on blue for selected

    # Completion menu styles (for input autocompletion)
    completion_menu: str = "bg:#333333 fg:#e0e0e0"  # Dark background
    completion_menu_completion: str = "bg:#333333 fg:#e0e0e0"  # Normal item
    completion_menu_completion_current: str = "bg:#0066cc fg:#ffffff"  # Selected item
    completion_menu_meta: str = "bg:#333333 fg:#888888"  # Meta/description text
    completion_menu_meta_current: str = "bg:#0066cc fg:#cccccc"  # Meta when selected
    scrollbar_background: str = "bg:#333333"  # Scrollbar track
    scrollbar_button: str = "bg:#666666"  # Scrollbar thumb

    # Markdown styles (for Rich rendering)
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
            # Dropdown menu
            'setting-dropdown': self.setting_dropdown,
            'setting-dropdown-border': self.setting_dropdown_border,
            'setting-dropdown-item': self.setting_dropdown_item,
            'setting-dropdown-selected': self.setting_dropdown_selected,
            # Completion menu
            'completion-menu': self.completion_menu,
            'completion-menu.completion': self.completion_menu_completion,
            'completion-menu.completion.current': self.completion_menu_completion_current,
            'completion-menu.meta': self.completion_menu_meta,
            'completion-menu.meta.current': self.completion_menu_meta_current,
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
