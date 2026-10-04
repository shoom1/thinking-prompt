"""
Styles for ThinkingPromptSession.

Provides ThinkingPromptStyles dataclass for clean style customization.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from prompt_toolkit.output import ColorDepth
from prompt_toolkit.styles import Style


def _fg(color: str) -> str:
    """'fg:<color>' or '' if the token is empty (mono/terminal themes)."""
    return f"fg:{color}" if color else ""


def _bg(color: str) -> str:
    """'bg:<color>' or '' if the token is empty."""
    return f"bg:{color}" if color else ""


def _style_str(*parts: str) -> str:
    """Join non-empty style parts with single spaces."""
    return " ".join(p for p in parts if p)


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
    - All element styles derive from `color_*` tokens; customize those
      properties to change colors throughout

    Element style fields hold explicit overrides only; "" (the default)
    means "derive from the tokens". Derivation happens when the Style is
    built (``to_style()``), so changing a token later — via
    ``dataclasses.replace()`` or by assignment — restyles every element
    you haven't overridden. A running session picks up a mutated instance
    on ``session.set_theme(styles)``. Use ``to_style_dict()`` to inspect
    the resolved styles.

    Example:
        styles = ThinkingPromptStyles(
            color_accent="#ff6600",  # Orange accent instead of cyan
            menu_item_selected="bg:#ff6600 fg:#ffffff",  # Orange selection
        )
        session = ThinkingPromptSession(theme=styles)

        # Tweak a built-in theme
        styles = dataclasses.replace(ThinkingPromptStyles.light(), color_error="#d00")
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
    color_thinking: str = "#a0a0a0"  # Thinking box + history thinking text
    color_thinking_border: str = "#606060"  # Thinking box border
    color_thinking_hint: str = "#707070"  # "+N lines..." expand hint
    color_bg_status: str = "#202040"  # Status bar background
    color_text_status: str = "#808090"  # Status bar text
    color_separator: str = "#444444"  # Input separator line
    color_bg_button: str = "#404040"  # Dialog button background
    color_bg_selected: str = "#454545"  # Selected menu/completion item bg
    color_shadow: str = "#000000"  # Dialog shadow

    # ==========================================================================
    # Shared menu styles - used by both dropdown and completion menus
    # ==========================================================================
    menu_bg: str = ""  # Defaults to color_bg_dark
    menu_item: str = ""  # Defaults to color_text on color_bg_dark
    menu_item_selected: str = ""  # Defaults to color_accent on color_bg_selected
    menu_border: str = ""  # Defaults to color_text_muted on color_bg_dark
    menu_meta: str = ""  # Defaults to color_text on color_bg_dark
    menu_meta_selected: str = ""  # Defaults to color_accent on color_bg_selected

    # ==========================================================================
    # Thinking box styles
    # ==========================================================================
    thinking_box: str = ""
    thinking_box_border: str = ""
    thinking_box_hint: str = ""

    # ==========================================================================
    # Status bar
    # ==========================================================================
    status_bar: str = ""

    # ==========================================================================
    # Chat history
    # ==========================================================================
    history: str = ""
    user_prefix: str = ""  # Defaults to color_accent on color_bg_input
    user_message: str = ""  # Defaults to color_text_bright on color_bg_input italic
    assistant_message: str = ""  # Defaults to color_text_bright
    thinking_message: str = ""
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
    input_separator: str = ""

    # ==========================================================================
    # Dialog styles
    # ==========================================================================
    dialog: str = ""  # Defaults to bg:color_bg_dialog
    dialog_title: str = ""  # Defaults to color_text_bright bold
    dialog_body: str = ""  # Defaults to color_text on color_bg_dialog
    dialog_border: str = ""  # Defaults to color_text_muted
    dialog_shadow: str = ""
    dialog_button: str = ""  # Defaults to color_text on color_bg_button
    dialog_button_focused: str = ""  # Defaults to color_text_bright on color_accent_button bold

    # ==========================================================================
    # Form controls
    # ==========================================================================
    radio_list: str = ""  # Defaults to color_text on color_bg_dialog
    radio_selected: str = ""  # Defaults to color_accent bold
    checkbox_list: str = ""  # Defaults to color_text on color_bg_dialog
    checkbox_selected: str = ""  # Defaults to color_accent bold
    text_area: str = ""  # Defaults to color_text_bright on color_bg_input
    select_arrow: str = ""  # Defaults to color_text_muted

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

    # ==========================================================================
    # Rendering hints
    # ==========================================================================
    color_depth: ColorDepth | None = None  # mono() sets DEPTH_1_BIT; None = terminal default.
    # Code highlighting for markdown fences and add_code(): a Pygments style
    # name, or "ansi_dark"/"ansi_light" for the terminal's own 16 colors.
    code_theme: str = "monokai"

    @classmethod
    def dark(cls) -> ThinkingPromptStyles:
        """The default dark theme (today's palette)."""
        return cls()

    @classmethod
    def light(cls) -> ThinkingPromptStyles:
        """Palette tuned for light terminal backgrounds."""
        return cls(
            color_accent="#0e7490",
            color_accent_button="#0066cc",
            color_success="#2e7d32",
            color_warning="#b45309",
            color_error="#b3261e",
            color_text="#1f2328",
            color_text_bright="#000000",
            color_text_muted="#6b7280",
            color_text_dim="#9ca3af",
            color_bg_dark="#e5e7eb",
            color_bg_dialog="#f3f4f6",
            color_bg_input="#e8eaed",
            color_thinking="#6b7280",
            color_thinking_border="#9ca3af",
            color_thinking_hint="#8a919c",
            color_bg_status="#dbeafe",
            color_text_status="#1e3a8a",
            color_separator="#d1d5db",
            color_bg_button="#d1d5db",
            color_bg_selected="#cbd5e1",
            color_shadow="#9ca3af",
            code_theme="default",
        )

    @classmethod
    def mono(cls) -> ThinkingPromptStyles:
        """Attributes only (bold/italic/reverse); rendered at 1-bit depth."""
        return cls(
            color_accent="", color_accent_button="", color_success="",
            color_warning="", color_error="", color_text="",
            color_text_bright="", color_text_muted="", color_text_dim="",
            color_bg_dark="", color_bg_dialog="", color_bg_input="",
            color_thinking="", color_thinking_border="", color_thinking_hint="",
            color_bg_status="", color_text_status="", color_separator="",
            color_bg_button="", color_bg_selected="", color_shadow="",
            # Selection/focus states need reverse video to stay visible.
            menu_item_selected="reverse",
            menu_meta_selected="reverse",
            dialog_button_focused="bold reverse",
            radio_selected="bold",
            checkbox_selected="bold",
            setting_label_selected="bold",
            setting_value_selected="italic",
            setting_desc_selected="italic",
            status_bar="reverse",
            color_depth=ColorDepth.DEPTH_1_BIT,
        )

    @classmethod
    def terminal(cls) -> ThinkingPromptStyles:
        """Named ANSI colors — inherits the terminal's own palette."""
        return cls(
            color_accent="ansicyan",
            color_accent_button="ansiblue",
            color_success="ansigreen",
            color_warning="ansiyellow",
            color_error="ansired",
            color_text="", color_text_bright="",
            color_text_muted="ansibrightblack",
            color_text_dim="ansibrightblack",
            color_bg_dark="", color_bg_dialog="", color_bg_input="",
            color_thinking="ansibrightblack",
            color_thinking_border="ansibrightblack",
            color_thinking_hint="ansibrightblack",
            color_bg_status="", color_text_status="ansiblue",
            color_separator="ansibrightblack",
            color_bg_button="", color_bg_selected="", color_shadow="",
            menu_item_selected="reverse",
            menu_meta_selected="reverse",
            dialog_button_focused="bold reverse",
            code_theme="ansi_dark",
        )

    def _derived(self) -> dict[str, str]:
        """Element styles derived from the color tokens (field name -> style).

        Consulted when the Style is built, for every element field left at
        "" — so token changes, via dataclasses.replace() or mutation,
        restyle everything that isn't explicitly overridden.
        """
        return {
            # Thinking box
            "thinking_box": _style_str(_fg(self.color_thinking), "italic"),
            "thinking_box_border": _fg(self.color_thinking_border),
            "thinking_box_hint": _style_str(_fg(self.color_thinking_hint), "italic"),
            "thinking_message": _style_str(_fg(self.color_thinking), "italic"),
            "status_bar": _style_str(_bg(self.color_bg_status), _fg(self.color_text_status)),
            "input_separator": _fg(self.color_separator),
            "dialog_shadow": _bg(self.color_shadow),
            # Menu styles
            "menu_bg": _bg(self.color_bg_dark),
            "menu_item": _style_str(_fg(self.color_text), _bg(self.color_bg_dark)),
            "menu_item_selected": _style_str(
                _fg(self.color_accent), _bg(self.color_bg_selected), "noreverse"
            ),
            "menu_border": _style_str(_fg(self.color_text_muted), _bg(self.color_bg_dark)),
            "menu_meta": _style_str(_fg(self.color_text), _bg(self.color_bg_dark)),
            "menu_meta_selected": _style_str(
                _fg(self.color_accent), _bg(self.color_bg_selected), "noreverse"
            ),
            # Chat history
            "user_prefix": _style_str(_fg(self.color_accent), _bg(self.color_bg_input)),
            "user_message": _style_str(
                _fg(self.color_text_bright), _bg(self.color_bg_input), "italic"
            ),
            "assistant_message": _fg(self.color_text_bright),
            "system_message": _fg(self.color_warning),
            # Status messages
            "error_message": _style_str(_fg(self.color_error), "bold"),
            "warning_message": _fg(self.color_warning),
            "success_message": _fg(self.color_success),
            # Dialog
            "dialog": _bg(self.color_bg_dialog),
            "dialog_title": _style_str(_fg(self.color_text_bright), "bold"),
            "dialog_body": _style_str(_bg(self.color_bg_dialog), _fg(self.color_text)),
            "dialog_border": _fg(self.color_text_muted),
            "dialog_button": _style_str(_bg(self.color_bg_button), _fg(self.color_text)),
            "dialog_button_focused": _style_str(
                _bg(self.color_accent_button), _fg(self.color_text_bright), "bold"
            ),
            # Form controls
            "radio_list": _style_str(_bg(self.color_bg_dialog), _fg(self.color_text)),
            "radio_selected": _style_str(_fg(self.color_accent), "bold"),
            "checkbox_list": _style_str(_bg(self.color_bg_dialog), _fg(self.color_text)),
            "checkbox_selected": _style_str(_fg(self.color_accent), "bold"),
            "text_area": _style_str(_bg(self.color_bg_input), _fg(self.color_text_bright)),
            "select_arrow": _fg(self.color_text_muted),
            # Settings list
            "setting_indicator": _fg(self.color_accent),
            "setting_label": _fg(self.color_text),
            "setting_label_selected": _fg(self.color_accent),
            "setting_value": _fg(self.color_text_muted),
            "setting_value_selected": _style_str(_fg(self.color_accent), "italic"),
            "setting_value_true": _fg(self.color_success),
            "setting_value_true_selected": _style_str(_fg(self.color_success), "italic"),
            "setting_value_false": _fg(self.color_text_muted),
            "setting_value_false_selected": _style_str(_fg(self.color_text_muted), "italic"),
            "setting_desc": _fg(self.color_text_dim),
            "setting_desc_selected": _fg(self.color_text_muted),
            # Scrollbar
            "scrollbar_background": _bg(self.color_bg_dark),
            "scrollbar_button": _bg(self.color_text_dim),
        }

    def to_style_dict(self) -> dict[str, str]:
        """
        The resolved style rules, by prompt_toolkit class name.

        Element fields left at "" are derived from the color tokens now,
        not at construction; explicitly set fields win. Useful for
        inspecting what a theme actually renders.

        Returns:
            The dict passed to ``Style.from_dict()`` by ``to_style()``.
        """
        derived = self._derived()

        def r(name: str) -> str:
            return getattr(self, name) or derived.get(name, "")

        return {
            'thinking-box': r("thinking_box"),
            'thinking-box.border': r("thinking_box_border"),
            'thinking-box.hint': r("thinking_box_hint"),
            'status': r("status_bar"),
            'history': r("history"),
            'history.user-prefix': r("user_prefix"),
            'history.user-message': r("user_message"),
            'history.assistant-message': r("assistant_message"),
            'history.thinking': r("thinking_message"),
            'history.system': r("system_message"),
            'history.error': r("error_message"),
            'history.warning': r("warning_message"),
            'history.success': r("success_message"),
            'prompt': r("prompt"),
            'input-separator': r("input_separator"),
            # Dialog styles
            'dialog': r("dialog"),
            'dialog.body': r("dialog_body"),
            'dialog frame.label': r("dialog_title"),
            'dialog frame.border': r("dialog_border"),
            'dialog shadow': r("dialog_shadow"),
            'button': r("dialog_button"),
            'button.focused': r("dialog_button_focused"),
            # Form controls
            'radio-list': r("radio_list"),
            'radio-selected': r("radio_selected"),
            'checkbox-list': r("checkbox_list"),
            'checkbox-selected': r("checkbox_selected"),
            'text-area': r("text_area"),
            'select-arrow': r("select_arrow"),
            # Settings list
            'setting-indicator': r("setting_indicator"),
            'setting-label': r("setting_label"),
            'setting-label-selected': r("setting_label_selected"),
            'setting-value': r("setting_value"),
            'setting-value-selected': r("setting_value_selected"),
            'setting-value-true': r("setting_value_true"),
            'setting-value-true-selected': r("setting_value_true_selected"),
            'setting-value-false': r("setting_value_false"),
            'setting-value-false-selected': r("setting_value_false_selected"),
            'setting-desc': r("setting_desc"),
            'setting-desc-selected': r("setting_desc_selected"),
            # Dropdown menu (uses shared menu styles)
            'setting-dropdown': r("menu_bg"),
            'setting-dropdown-border': r("menu_border"),
            'setting-dropdown-item': r("menu_item"),
            'setting-dropdown-selected': r("menu_item_selected"),
            # Completion menu (uses shared menu styles)
            'completion-menu': r("menu_bg"),
            'completion-menu.completion': r("menu_item"),
            'completion-menu.completion.current': r("menu_item_selected"),
            'completion-menu.meta': r("menu_meta"),
            'completion-menu.meta.completion': r("menu_meta"),
            'completion-menu.meta.completion.current': r("menu_meta_selected"),
            'scrollbar.background': r("scrollbar_background"),
            'scrollbar.button': r("scrollbar_button"),
        }

    def to_style(self) -> Style:
        """
        Convert to prompt_toolkit Style object.

        Returns:
            A Style object for use with prompt_toolkit Application.
        """
        return Style.from_dict(self.to_style_dict())

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


THEMES: dict[str, Callable[[], ThinkingPromptStyles]] = {
    "dark": ThinkingPromptStyles.dark,
    "light": ThinkingPromptStyles.light,
    "mono": ThinkingPromptStyles.mono,
    "terminal": ThinkingPromptStyles.terminal,
}


def _resolve_auto() -> ThinkingPromptStyles:
    """NO_COLOR -> mono; COLORFGBG -> light/dark; else terminal-native."""
    if os.environ.get("NO_COLOR"):
        return ThinkingPromptStyles.mono()
    colorfgbg = os.environ.get("COLORFGBG", "")
    parts = colorfgbg.split(";")
    # A COLORFGBG without a fg;bg pair is not a value we trust.
    if len(parts) >= 2:
        try:
            bg = int(parts[-1])
        except ValueError:
            pass
        else:
            if bg in (7, 15):
                return ThinkingPromptStyles.light()
            return ThinkingPromptStyles.dark()
    return ThinkingPromptStyles.terminal()


def resolve_theme(theme: str | ThinkingPromptStyles) -> ThinkingPromptStyles:
    """Resolve a theme name or instance to a ThinkingPromptStyles.

    Raises:
        ValueError: For unknown theme names.
    """
    if isinstance(theme, ThinkingPromptStyles):
        return theme
    if theme == "auto":
        return _resolve_auto()
    try:
        return THEMES[theme]()
    except KeyError:
        valid = ", ".join([*sorted(THEMES), "auto"])
        raise ValueError(f"Unknown theme {theme!r}. Valid themes: {valid}") from None


# Default styles instance
DEFAULT_STYLES = ThinkingPromptStyles()
