"""
Styles for ThinkingPromptSession.

Provides ThinkingPromptStyles dataclass for clean style customization.
"""
from __future__ import annotations

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
    # Base theme colors - customize these to change colors throughout.
    # The defaults are the terminal theme's: named ANSI colors, which the
    # terminal maps to its own palette, and no backgrounds ("": the
    # terminal's own). dark() and light() set fixed palettes instead.
    # ==========================================================================
    color_accent: str = "ansicyan"  # Primary accent (selection, indicators)
    color_accent_button: str = "ansiblue"  # Button/menu selection highlight
    color_success: str = "ansigreen"  # Success states
    color_warning: str = "ansiyellow"  # Warnings, system messages
    color_error: str = "ansired"  # Errors
    color_text: str = ""  # Primary text
    color_text_bright: str = ""  # Emphasized text
    color_text_muted: str = "ansibrightblack"  # Secondary/muted text
    color_text_dim: str = "ansibrightblack"  # Very dim text
    color_bg_dark: str = ""  # Menus, dropdowns
    color_bg_dialog: str = ""  # Dialog background
    color_bg_input: str = ""  # Input fields, highlights
    color_thinking: str = "ansibrightblack"  # Thinking box + echoed thinking text
    color_thinking_border: str = "ansibrightblack"  # Thinking box border
    color_thinking_hint: str = "ansibrightblack"  # "+N lines..." expand hint
    color_bg_status: str = ""  # Status bar background
    color_text_status: str = "ansiblue"  # Status bar text
    color_separator: str = "ansibrightblack"  # Input separator line
    color_bg_button: str = ""  # Dialog button background
    color_bg_selected: str = ""  # Selected menu/completion item bg
    color_shadow: str = ""  # Dialog shadow

    # ==========================================================================
    # Shared menu styles - used by both dropdown and completion menus
    # ==========================================================================
    menu_bg: str = ""  # Defaults to color_bg_dark
    menu_item: str = ""  # Defaults to color_text on color_bg_dark
    # The default theme shows selections in reverse video (it has no
    # background colors); "" derives color_accent on color_bg_selected.
    menu_item_selected: str = "reverse"
    menu_border: str = ""  # Defaults to color_text_muted on color_bg_dark
    menu_meta: str = ""  # Defaults to color_text on color_bg_dark
    menu_meta_selected: str = "reverse"  # "": color_accent on color_bg_selected

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
    # The transcript: what the session prints
    # ==========================================================================
    transcript: str = ""
    user_prefix: str = ""  # Defaults to color_accent on color_bg_input
    user_message: str = ""  # Defaults to color_text_bright on color_bg_input italic
    assistant_message: str = ""  # Defaults to color_text_bright
    thinking_message: str = ""
    system_message: str = ""  # Defaults to color_warning
    queued_input: str = ""  # Defaults to color_text_muted italic

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
    dialog_button_focused: str = "bold reverse"  # "": color_text_bright on color_accent_button bold
    dialog_choice: str = ""  # Inline action rows. Defaults to color_text
    dialog_choice_selected: str = ""  # Highlighted action row, and a ChoiceField's pick. Defaults to color_accent bold
    dialog_hint: str = ""  # Inline dialog key hint. Defaults to color_text_muted italic

    # ==========================================================================
    # Form controls
    # ==========================================================================
    text_area: str = ""  # Defaults to color_text_bright on color_bg_input
    select_arrow: str = ""  # Defaults to color_text_muted
    checkbox_mark: str = ""  # [x] / (•) marks of check and radio lists. Defaults to color_accent

    # ==========================================================================
    # Dialog form fields
    # ==========================================================================
    field_indicator: str = ""  # Defaults to color_accent
    field_label: str = ""  # Defaults to color_text
    field_label_selected: str = ""  # Defaults to color_accent
    field_value: str = ""  # Defaults to color_text_muted
    field_value_selected: str = ""  # Defaults to color_accent italic
    field_value_true: str = ""  # Defaults to color_success
    field_value_true_selected: str = ""  # Defaults to color_success italic
    field_value_false: str = ""  # Defaults to color_text_muted
    field_value_false_selected: str = ""  # Defaults to color_text_muted italic
    field_desc: str = ""  # Defaults to color_text_dim
    field_desc_selected: str = ""  # Defaults to color_text_muted

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
    code_theme: str = "ansi_dark"

    @classmethod
    def dark(cls) -> ThinkingPromptStyles:
        """A fixed palette for dark terminal backgrounds (0.4's default):
        hex colors, with backgrounds on the status bar, dialogs and menus."""
        return cls(
            color_accent="#88c0d0",
            color_accent_button="#0066cc",
            color_success="#a3be8c",
            color_warning="#ebcb8b",
            color_error="#bf616a",
            color_text="#e0e0e0",
            color_text_bright="#ffffff",
            color_text_muted="#888888",
            color_text_dim="#666666",
            color_bg_dark="#333333",
            color_bg_dialog="#2a2a2a",
            color_bg_input="#3a3a3a",
            color_thinking="#a0a0a0",
            color_thinking_border="#606060",
            color_thinking_hint="#707070",
            color_bg_status="#202040",
            color_text_status="#808090",
            color_separator="#444444",
            color_bg_button="#404040",
            color_bg_selected="#454545",
            color_shadow="#000000",
            # Selections by background color: "" derives them from the
            # tokens, in place of the default's reverse video.
            menu_item_selected="",
            menu_meta_selected="",
            dialog_button_focused="",
            code_theme="monokai",
        )

    @classmethod
    def light(cls) -> ThinkingPromptStyles:
        """A fixed palette for light terminal backgrounds."""
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
            # Selections by background color: "" derives them from the
            # tokens, in place of the default's reverse video.
            menu_item_selected="",
            menu_meta_selected="",
            dialog_button_focused="",
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
            field_label_selected="bold",
            field_value_selected="italic",
            field_desc_selected="italic",
            status_bar="reverse",
            color_depth=ColorDepth.DEPTH_1_BIT,
        )

    @classmethod
    def terminal(cls) -> ThinkingPromptStyles:
        """The default: named ANSI colors, so the terminal's own palette
        (light or dark), with no backgrounds; selections in reverse video."""
        return cls()

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
            # The transcript
            "user_prefix": _style_str(_fg(self.color_accent), _bg(self.color_bg_input)),
            "user_message": _style_str(
                _fg(self.color_text_bright), _bg(self.color_bg_input), "italic"
            ),
            "assistant_message": _fg(self.color_text_bright),
            "system_message": _fg(self.color_warning),
            "queued_input": _style_str(_fg(self.color_text_muted), "italic"),
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
            "dialog_choice": _fg(self.color_text),
            "dialog_choice_selected": _style_str(_fg(self.color_accent), "bold"),
            "dialog_hint": _style_str(_fg(self.color_text_muted), "italic"),
            # Form controls
            "text_area": _style_str(_bg(self.color_bg_input), _fg(self.color_text_bright)),
            "select_arrow": _fg(self.color_text_muted),
            "checkbox_mark": _fg(self.color_accent),
            # Dialog form fields
            "field_indicator": _fg(self.color_accent),
            "field_label": _fg(self.color_text),
            "field_label_selected": _fg(self.color_accent),
            "field_value": _fg(self.color_text_muted),
            "field_value_selected": _style_str(_fg(self.color_accent), "italic"),
            "field_value_true": _fg(self.color_success),
            "field_value_true_selected": _style_str(_fg(self.color_success), "italic"),
            "field_value_false": _fg(self.color_text_muted),
            "field_value_false_selected": _style_str(_fg(self.color_text_muted), "italic"),
            "field_desc": _fg(self.color_text_dim),
            "field_desc_selected": _fg(self.color_text_muted),
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
            'transcript': r("transcript"),
            'transcript.user-prefix': r("user_prefix"),
            'transcript.user-message': r("user_message"),
            'transcript.assistant-message': r("assistant_message"),
            'transcript.thinking': r("thinking_message"),
            'transcript.system': r("system_message"),
            'transcript.error': r("error_message"),
            'transcript.warning': r("warning_message"),
            'transcript.success': r("success_message"),
            'queued-input': r("queued_input"),
            'prompt': r("prompt"),
            'input-separator': r("input_separator"),
            # Dialog styles
            'dialog': r("dialog"),
            'dialog.body': r("dialog_body"),
            'dialog frame.label': r("dialog_title"),
            'dialog-title': r("dialog_title"),  # inline dialogs
            'dialog frame.border': r("dialog_border"),
            'dialog shadow': r("dialog_shadow"),
            'button': r("dialog_button"),
            'button.focused': r("dialog_button_focused"),
            'dialog-choice': r("dialog_choice"),
            'dialog-choice-selected': r("dialog_choice_selected"),
            'dialog-hint': r("dialog_hint"),
            # Form controls
            'text-area': r("text_area"),
            'select-arrow': r("select_arrow"),
            'checkbox-mark': r("checkbox_mark"),
            # Form fields
            'field-indicator': r("field_indicator"),
            'field-label': r("field_label"),
            'field-label-selected': r("field_label_selected"),
            'field-value': r("field_value"),
            'field-value-selected': r("field_value_selected"),
            'field-value-true': r("field_value_true"),
            'field-value-true-selected': r("field_value_true_selected"),
            'field-value-false': r("field_value_false"),
            'field-value-false-selected': r("field_value_false_selected"),
            'field-desc': r("field_desc"),
            'field-desc-selected': r("field_desc_selected"),
            # Dropdown menu (uses shared menu styles)
            'field-dropdown': r("menu_bg"),
            'field-dropdown-border': r("menu_border"),
            'field-dropdown-item': r("menu_item"),
            'field-dropdown-selected': r("menu_item_selected"),
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

    def _rich_theme_dict(self) -> dict[str, str]:
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


def resolve_theme(theme: str | ThinkingPromptStyles) -> ThinkingPromptStyles:
    """Resolve a theme name or instance to a ThinkingPromptStyles.

    Raises:
        ValueError: For unknown theme names.
    """
    if isinstance(theme, ThinkingPromptStyles):
        return theme
    try:
        return THEMES[theme]()
    except KeyError:
        valid = ", ".join(sorted(THEMES))
        raise ValueError(f"Unknown theme {theme!r}. Valid themes: {valid}") from None
