"""
ThinkingPromptSession - A chat-like interface with thinking box.

This module provides a PromptSession-like interface that adds a thinking box
above the input. The thinking box appears when processing user input and
can be expanded to full-screen mode with chat history.
"""
from __future__ import annotations

import asyncio
import os
import threading
import warnings
from collections.abc import AsyncIterator, Coroutine, Sequence
from contextlib import asynccontextmanager, suppress
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Literal,
    Optional,
    cast,
)

if TYPE_CHECKING:
    from .dialog import BaseDialog, DialogConfig, DialogManager
    from .settings_dialog import SettingsItem
    from .types import ContentFormat

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer
from prompt_toolkit.enums import DEFAULT_BUFFER, EditingMode
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.formatted_text import AnyFormattedText, FormattedText
from prompt_toolkit.history import History, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.styles import DynamicStyle

from .app_info import AppInfo
from .display import Display
from .layout import create_layout
from .manager import ThinkingBoxManager
from .rich_utils import _is_rich_renderable
from .styles import DEFAULT_STYLES, ThinkingPromptStyles, resolve_theme
from .types import ThinkingContext


class ThinkingPromptSession:
    """
    A chat-like prompt session with a thinking box.

    This class provides a prompt interface similar to PromptSession but with
    additional features:
    - A thinking box that appears above the input during processing
    - Expand/collapse functionality (Ctrl+E) for the thinking box
    - Automatic transition to full-screen mode when expanded
    - Chat history visible in full-screen mode

    The handler decides whether to use thinking mode by calling start_thinking()
    with a content callback. This allows flexible control over when the thinking
    box appears.

    Example:
        app_info = AppInfo(name="MyApp", version="1.0.0")
        session = ThinkingPromptSession(app_info=app_info)

        @session.on_input
        async def handle(user_input: str):
            if not user_input.strip():
                return

            async with session.thinking() as ctx:
                ctx.append("Processing...\\n")
                await asyncio.sleep(1)
                ctx.append("Done!\\n")

            session.add_response(f"Echo: {user_input}")

        await session.run_async()
    """

    def __init__(
        self,
        message: AnyFormattedText = ">>> ",
        app_info: AppInfo | None = None,
        styles: ThinkingPromptStyles | None = None,
        theme: str | ThinkingPromptStyles | None = None,
        history: History | None = None,
        completer: Completer | None = None,
        complete_while_typing: bool = False,
        completions_menu_height: int = 5,
        editing_mode: EditingMode = EditingMode.EMACS,
        max_thinking_height: int = 15,
        enable_status_bar: bool = True,
        status_text: AnyFormattedText = "Ctrl+C: cancel | Ctrl+D: exit",
        echo_input: bool = True,
        history_limit: int | None = None,
    ) -> None:
        """
        Initialize the ThinkingPromptSession.

        Args:
            message: The prompt message to display.
            app_info: Application info (name, version, welcome message).
            styles: Custom styles for the session.
            theme: Theme name ('dark', 'light', 'mono', 'terminal', 'auto') or
                   ThinkingPromptStyles instance. Cannot be used with styles=.
            history: History object for input history.
            completer: Completer for input autocompletion.
            complete_while_typing: Show completions automatically while typing.
            completions_menu_height: Maximum height of completions dropdown menu.
            editing_mode: Editing mode (EMACS or VI).
            max_thinking_height: Max lines for collapsed thinking box (must be >= 2).
            enable_status_bar: Whether to show status bar.
            status_text: Text to display in status bar.
            echo_input: Whether to echo user input to console before thinking.
            history_limit: Max transcript entries kept for fullscreen history
                          and repaint; oldest trimmed. None = unbounded.

        Raises:
            ValueError: If max_thinking_height is less than 2, or if both theme=
                       and styles= are provided.
        """
        if max_thinking_height < 2:
            raise ValueError("max_thinking_height must be at least 2")

        self._message = message
        self._app_info = app_info

        # Handle theme vs styles parameters
        if theme is not None and styles is not None:
            raise ValueError(
                "Pass either theme= or styles=, not both. theme= accepts a "
                "name ('dark', 'light', 'mono', 'terminal', 'auto') or a "
                "ThinkingPromptStyles instance."
            )
        if theme is not None:
            self._styles = resolve_theme(theme)
        else:
            self._styles = styles or DEFAULT_STYLES

        # NO_COLOR is read once at construction (no-color.org: non-empty).
        self._no_color = bool(os.environ.get("NO_COLOR"))

        self._max_thinking_height = max_thinking_height
        self._enable_status_bar = enable_status_bar
        self._status_text = status_text
        self._editing_mode = editing_mode
        self._echo_input = echo_input
        self._completer = completer
        self._complete_while_typing = complete_while_typing
        self._completions_menu_height = completions_menu_height

        # Fullscreen state (thread-safe)
        self._is_fullscreen: bool = False
        self._fullscreen_lock = threading.RLock()
        self._pre_fullscreen_expanded: bool | None = None
        # Set by set_theme(repaint=True) while in fullscreen; consumed by
        # switch_to_prompt(), which repaints instead of flushing pending output.
        self._repaint_on_fullscreen_exit: bool = False

        # Convert styles dataclass to prompt_toolkit Style
        self._style = self._styles.to_style()

        # Display handles all output to console and history
        self._display = Display(
            get_style=lambda: self._style,
            is_fullscreen=lambda: self.is_fullscreen,  # Use property for thread safety
            thinking_styles=self._styles,
            get_color_depth=self._effective_color_depth,
            history_limit=history_limit,
        )

        # Get key bindings and feature flags from app_info or use defaults
        self._fullscreen_key = app_info.fullscreen_key if app_info else "c-e"
        self._expand_key = app_info.expand_key if app_info else "c-t"
        self._fullscreen_enabled = app_info.fullscreen_enabled if app_info else False
        self._echo_thinking = app_info.echo_thinking if app_info else True

        # Thinking box manager (manages multiple thinking boxes).
        # expand_key flows through to each box so the truncation hint
        # matches the key bound below in _create_key_bindings.
        self._manager = ThinkingBoxManager(
            default_max_lines=max_thinking_height,
            expand_key=self._expand_key,
        )

        # Input history (for up/down arrow)
        self._input_history = history or InMemoryHistory()

        # Input handler callback (can be set via @on_input decorator or run_async)
        # Handler can be sync (returns None) or async (returns Coroutine)
        self._input_handler: Callable[[str], None | Coroutine[Any, Any, None]] | None = None

        # Pending input future for async handling
        self._pending_input: asyncio.Future[str] | None = None

        # Currently running handler task (set by _run_handler while a user
        # input handler is executing). Ctrl+C cancels this task; the input
        # buffer's accept_handler refuses new input while it is running.
        self._current_handler_task: asyncio.Task[None] | None = None
        # Set to True by the Ctrl+C binding when it cancels the handler task.
        # _run_handler reads this to distinguish a user-initiated cancel
        # (swallow CancelledError, continue the input loop) from an outer
        # cancellation (re-raise to let the input loop exit).
        self._user_cancelled_handler: bool = False

        # Dialog manager (lazy initialization)
        self._dialog_manager: DialogManager | None = None

        # Create components
        self.default_buffer = self._create_default_buffer()
        self.layout = self._create_session_layout()
        self.app = self._create_application()

        # Set up history change callback for UI invalidation
        self._display.set_on_change(self._invalidate)

    def _get_prompt_string(self) -> str:
        """Get the prompt as a plain string."""
        msg: Any = self._message
        if callable(msg):
            msg = msg()
        if isinstance(msg, str):
            return msg
        if msg is None:
            return ""
        if hasattr(msg, '__iter__'):
            return ''.join(item[1] if isinstance(item, tuple) else str(item) for item in msg)
        return str(msg)

    def _create_default_buffer(self) -> Buffer:
        """Create the main input buffer."""

        def accept_handler(buff: Buffer) -> bool:
            """Handle input acceptance."""
            # Refuse to deliver input while a handler is already running.
            # If we accepted, the new text would be echoed and the buffer
            # cleared, but the handler couldn't pick it up — it would just
            # vanish. Instead leave the buffer intact and surface a hint
            # so the user knows why nothing happened.
            if (
                self._current_handler_task is not None
                and not self._current_handler_task.done()
            ):
                self.set_status("Busy — press Ctrl+C to cancel")
                return False

            text = buff.document.text

            # Add to input history (for up/down arrow)
            if text.strip():
                self._input_history.append_string(text)

                if self._echo_input:
                    # Echo user input to console and history
                    prompt_str = self._get_prompt_string()
                    self._display.user_input(prompt_str, text)

            # Signal that input is ready - handler decides whether to use thinking mode
            if self._pending_input and not self._pending_input.done():
                self._pending_input.set_result(text)

            # Clear buffer for next input
            buff.reset()
            return True

        return Buffer(
            name=DEFAULT_BUFFER,
            history=self._input_history,
            completer=self._completer,
            complete_while_typing=self._complete_while_typing,
            accept_handler=accept_handler,
            multiline=False,
        )

    def _create_session_layout(self) -> Any:
        """Create the layout using the layout module."""
        self._default_thinking_text = (
            self._app_info.thinking_text if self._app_info else "Thinking"
        )
        # Store header config from app_info for per-box headers
        self._header_config: dict[str, Any] = {}
        if self._app_info:
            self._header_config = {
                "frames": self._app_info.thinking_animation,
                "position": self._app_info.thinking_animation_position,
            }

        return create_layout(
            default_buffer=self.default_buffer,
            message=lambda: self._message,
            max_thinking_height=self._max_thinking_height,
            history=self._display.history,
            is_fullscreen=lambda: self._is_fullscreen,
            get_status_text=lambda: self._status_text,
            is_status_bar_enabled=lambda: self._enable_status_bar,
            thinking_manager=self._manager,
            completions_menu_height=self._completions_menu_height,
        )

    def _create_application(self) -> Application:
        """Create the Application object."""

        # Key bindings
        kb = self._create_key_bindings()

        return Application(
            layout=self.layout,
            style=DynamicStyle(lambda: self._style),
            key_bindings=kb,
            editing_mode=self._editing_mode,
            full_screen=False,  # Start in normal mode, will be updated dynamically
            mouse_support=Condition(lambda: self._is_fullscreen),  # Only in fullscreen
            refresh_interval=0.1,  # For real-time updates
            color_depth=self._effective_color_depth,
        )

    def _create_key_bindings(self) -> KeyBindings:
        """Create key bindings for the session."""
        kb = KeyBindings()

        # Cancel/interrupt — cancel the running handler, finish boxes,
        # cancel pending input. Falls through to app.exit() when no
        # handler was running and no boxes were active. A live pending
        # input future does NOT count as in-flight work: it merely means
        # the prompt is waiting for input, which is the idle state.
        @kb.add("c-c")
        def cancel(event: KeyPressEvent) -> None:
            """Cancel current operation or exit."""
            # Snapshot state BEFORE we mutate anything. Otherwise the final
            # idle check below would re-read state we just cleared (e.g.
            # has_active_boxes after finish_all) and incorrectly conclude
            # there was nothing to cancel, triggering app.exit().
            handler_running = (
                self._current_handler_task is not None
                and not self._current_handler_task.done()
            )
            had_active_boxes = self._manager.has_active_boxes
            had_pending_input = (
                self._pending_input is not None
                and not self._pending_input.done()
            )

            if handler_running:
                # Mark before cancel so _run_handler treats this as a user
                # cancellation and does not re-raise CancelledError.
                self._user_cancelled_handler = True
                assert self._current_handler_task is not None
                self._current_handler_task.cancel()

            if had_active_boxes:
                self._manager.finish_all()
                self._invalidate()

            if had_pending_input:
                assert self._pending_input is not None
                self._pending_input.cancel()

            if not handler_running and not had_active_boxes:
                # No handler and no boxes — the session is idle, so Ctrl+C
                # means "exit". At an idle prompt the pending-input future
                # is always live (prompt_async is awaiting it), so it must
                # not count as in-flight work: treating it as such used to
                # kill the input loop while leaving the app running, after
                # which typed input was echoed but silently dropped. The
                # future was cancelled above, so direct prompt_async()
                # callers still observe KeyboardInterrupt; app.exit() ends
                # run_async()'s own loop either way.
                event.app.exit()

        # Exit (EOF) — only on an empty input line, matching readline
        # semantics. With text in the buffer this binding is inactive and
        # prompt_toolkit's default emacs binding (delete-char) handles the
        # key, so a typed draft is never destroyed by a stray Ctrl+D.
        @kb.add("c-d", filter=Condition(lambda: not self.default_buffer.text))
        def exit_app(event: KeyPressEvent) -> None:
            """Exit the application."""
            # Resolve the pending future so direct prompt_async() callers
            # observe the documented EOFError instead of hanging forever.
            if self._pending_input is not None and not self._pending_input.done():
                self._pending_input.set_exception(EOFError())
            event.app.exit()

        # Enter to submit (when not thinking)
        @kb.add("enter", filter=has_focus(DEFAULT_BUFFER))
        def accept_input(event: KeyPressEvent) -> None:
            """Accept input."""
            self.default_buffer.validate_and_handle()

        # Expand/collapse — toggle all via manager
        def can_toggle() -> bool:
            if not self._manager.can_toggle():
                return False
            return not self._is_fullscreen

        @kb.add(self._expand_key, filter=Condition(can_toggle))
        def toggle_expand(event: KeyPressEvent) -> None:
            self._manager.toggle_all()
            self._invalidate()

        # Fullscreen toggle key binding (only when enabled)
        if self._fullscreen_enabled:
            @kb.add(self._fullscreen_key)
            def toggle_fullscreen(event: KeyPressEvent) -> None:
                """Toggle fullscreen mode."""
                if self._is_fullscreen:
                    self.switch_to_prompt()
                else:
                    if self._manager.has_active_boxes:
                        self._pre_fullscreen_expanded = self._manager.is_expanded
                        self._manager.expand_all()
                    self.switch_to_fullscreen()

        return kb

    def _effective_color_depth(self) -> ColorDepth | None:
        """NO_COLOR (env, at construction) wins; else the theme's hint."""
        if self._no_color:
            return ColorDepth.DEPTH_1_BIT
        return self._styles.color_depth

    @property
    def styles(self) -> ThinkingPromptStyles:
        """The active theme's styles instance."""
        return self._styles

    def set_theme(
        self, theme: str | ThinkingPromptStyles, repaint: bool = False
    ) -> None:
        """Switch the active theme at runtime.

        The live UI (prompt, thinking boxes, dialogs, fullscreen history)
        re-renders in the new theme on the next paint. Content already
        printed to the terminal (prompt-mode scrollback) keeps its
        original colors — only the Display's ``get_style`` callable and
        the Application's ``DynamicStyle`` are re-read; scrollback lines
        already written to the terminal are not retroactively recolored,
        unless ``repaint=True`` is passed.

        Args:
            theme: Theme name ('dark', 'light', 'mono', 'terminal', 'auto')
                or a ThinkingPromptStyles instance.
            repaint: If True, clear the screen and scrollback and re-print
                the transcript in the new theme. Markdown and code re-render
                from source; rich/raw ANSI keeps its original colors. In
                fullscreen mode the repaint is deferred to fullscreen exit,
                replacing the pending-output flush.

        Raises:
            ValueError: For unknown theme names.
        """
        resolved = resolve_theme(theme)
        self._styles = resolved
        self._style = resolved.to_style()
        self._display.set_theme(resolved)
        if repaint:
            if self.is_fullscreen:
                self._repaint_on_fullscreen_exit = True
            else:
                self._repaint_console()
        self._invalidate()

    def _repaint_console(self) -> None:
        """Clear screen + scrollback and re-print the transcript."""
        if self.app and self.app.is_running:
            self.app.renderer.clear()
            # Renderer.clear() resets the screen model; scrollback erase is
            # not part of its contract, so emit CSI 3J directly.
            self.app.output.write_raw("\x1b[3J")
            self.app.output.flush()
        else:
            print("\x1b[2J\x1b[H\x1b[3J", end="", flush=True)
        self._display.reprint_transcript()

    def _invalidate(self) -> None:
        """Trigger UI refresh and update full_screen state."""
        if self.app:
            # Update full_screen based on state
            # prompt_toolkit handles alternate buffer switching automatically
            self.app.full_screen = self._is_fullscreen

            if self.app.is_running:
                self.app.invalidate()

    # =========================================================================
    # Welcome Message
    # =========================================================================

    def _print_welcome(self) -> None:
        """Print the welcome message before starting the app."""
        if self._app_info is None:
            return

        content = self._app_info.get_welcome_content()
        self._display.welcome(content)

    # =========================================================================
    # Thinking API
    # =========================================================================

    def start_thinking(
        self,
        content_callback: Callable[[], str] | None = None,
        *,
        title: str | None = None,
        order: int = 0,
        max_lines: int | None = None,
        content_format: ContentFormat = "plain",
    ) -> ThinkingContext:
        """
        Start the thinking state with a content callback.

        The callback is called repeatedly to get the current content for the
        thinking box. This allows dynamic content that updates in real-time.

        The callback must be thread-safe if called from multiple threads.

        Args:
            content_callback: Callable that returns the current thinking content.
                If None, a StreamingContent is created internally.
            title: Optional title to set on the thinking separator.
            order: Sort key for multiple boxes (higher = closer to prompt).
            max_lines: Max collapsed lines (overrides session default).
            content_format: Format for rendering ("plain" or "ansi").

        Returns:
            ThinkingContext for title control and content management.

        Example:
            content = ""

            def get_content():
                return content

            ctx = session.start_thinking(get_content, title="Processing")

            # Update content dynamically
            content += "Processing...\\n"
            await asyncio.sleep(0.5)
            ctx.set_title("Finishing")
            content += "Done!\\n"

            ctx.finish()
        """
        # Always provide a title so a header is created for every box
        effective_title = title if title is not None else self._default_thinking_text
        box = self._manager.create_box(
            content_callback=content_callback,
            title=effective_title,
            order=order,
            max_lines=max_lines,
            content_format=content_format,
        )

        # Apply header config from app_info
        if box.header and self._header_config:
            if self._header_config.get("frames") is not None:
                box.header.frames = self._header_config["frames"]
            if self._header_config.get("position") is not None:
                box.header.position = self._header_config["position"]

        self._invalidate()

        # Build finish callback for this specific box
        def _finish_box(
            add_to_history: bool = True,
            echo_to_console: bool | None = None,
        ) -> str:
            full_content, _, content_format_val = self._manager.remove_box(box.box_id)
            should_echo = (
                echo_to_console if echo_to_console is not None else self._echo_thinking
            )
            if full_content.strip():
                self._display.thinking(
                    full_content,
                    truncate_lines=box.control.max_collapsed_lines,
                    add_to_history=add_to_history,
                    echo_to_console=should_echo,
                    content_format=content_format_val,
                )
            self._invalidate()
            return full_content

        return ThinkingContext(
            content=box.streaming_content,
            set_title=lambda t: setattr(box.header, 'text', t) if box.header else None,
            get_title=lambda: box.header.text if box.header else self._default_thinking_text,
            set_format=box.control.set_content_format,
            rich_theme=self._display.rich_theme,
            finish=_finish_box,
        )

    def finish_thinking(
        self,
        add_to_history: bool = True,
        echo_to_console: bool | None = None,
    ) -> str:
        """
        Complete the thinking phase (finishes all active boxes).

        .. deprecated::
            Use ``ThinkingContext.finish()`` on the context returned by
            ``start_thinking()``, or use the ``thinking()`` async context
            manager for automatic per-box lifecycle management.

        Console gets collapsed/truncated version (for prompt mode).
        History gets full content (for fullscreen mode).

        Args:
            add_to_history: If True, add thinking content to chat history.
            echo_to_console: If True, print thinking content to console.
                            If None (default), uses AppInfo.echo_thinking setting.

        Returns:
            The full thinking content that was displayed.
        """
        warnings.warn(
            "finish_thinking() is deprecated. Use ctx.finish() on the "
            "ThinkingContext returned by start_thinking(), or use the "
            "thinking() async context manager instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if not self._manager.has_active_boxes:
            return ""

        should_echo = (
            echo_to_console if echo_to_console is not None else self._echo_thinking
        )

        results = self._manager.finish_all()
        all_content = []

        for _box_id, full_content, _, content_format_val, max_lines in results:
            if full_content.strip():
                self._display.thinking(
                    full_content,
                    # Truncate to each box's own limit, matching the
                    # per-box finish path (_finish_box).
                    truncate_lines=max_lines,
                    add_to_history=add_to_history,
                    echo_to_console=should_echo,
                    content_format=content_format_val,
                )
                all_content.append(full_content)

        self._invalidate()
        return "\n".join(all_content)

    @property
    def is_thinking(self) -> bool:
        """Check if currently in thinking state."""
        return self._manager.has_active_boxes

    @asynccontextmanager
    async def thinking(
        self,
        *,
        title: str | None = None,
        content_format: ContentFormat = "plain",
        add_to_history: bool = True,
        echo_to_console: bool | None = None,
        order: int = 0,
        max_lines: int | None = None,
    ) -> AsyncIterator[ThinkingContext]:
        """
        Context manager for thinking operations.

        Provides a more Pythonic way to manage thinking state with automatic
        cleanup. Returns a ThinkingContext for content accumulation and
        title control.

        Args:
            title: Optional title for the thinking separator.
            content_format: Format for rendering ("plain" or "ansi").
            add_to_history: If True, add thinking content to chat history
                when exiting the context.
            echo_to_console: If True, print thinking content to console.
                            If None (default), uses AppInfo.echo_thinking setting.
            order: Sort key for multiple boxes (higher = closer to prompt).
            max_lines: Max collapsed lines (overrides session default).

        Yields:
            ThinkingContext: Content accumulator with title control.

        Example:
            async with session.thinking(title="Processing") as ctx:
                ctx.append("Working...\\n")
                await asyncio.sleep(1)
                ctx.set_title("Finishing")
                ctx.append("Done!\\n")

            # Thinking is automatically finished when exiting the context

        Example with Rich-styled lines:
            async with session.thinking() as ctx:
                ctx.append_rich("[dim]  Step 1: Load data[/dim]\\n")
                ctx.append_rich("[dim]  Step 2: Process[/dim]\\n")

                await do_step_1()
                ctx.set_line_rich(0, "[green]✓ Step 1: Load data[/green]")
                ctx.set_line_rich(1, "[bold]⟳ Step 2: Processing...[/bold]")

                await do_step_2()
                ctx.set_line_rich(1, "[green]✓ Step 2: Process[/green]")

        Note:
            If an exception occurs within the context, thinking is still
            finished properly but content is not added to history.
        """
        ctx = self.start_thinking(
            title=title,
            content_format=content_format,
            order=order,
            max_lines=max_lines,
        )
        try:
            yield ctx
            ctx.finish(add_to_history=add_to_history, echo_to_console=echo_to_console)
        except BaseException:
            ctx.finish(add_to_history=False, echo_to_console=False)
            raise

    # =========================================================================
    # Chat History API
    # =========================================================================

    def add_response(
        self,
        content: str | FormattedText,
        *,
        markdown: bool = False,
    ) -> None:
        """
        Add a response to history and console.

        This is the primary method for displaying assistant responses. Supports
        plain text, markdown, or pre-formatted FormattedText.

        Args:
            content: The response content (str or FormattedText).
            markdown: If True and content is str, render as markdown via Rich.
                     Falls back to plain text if Rich is not installed.

        Examples:
            # Plain text
            session.add_response("Hello, world!")

            # Markdown (rendered via Rich)
            session.add_response("# Title\\n- Item 1\\n- Item 2", markdown=True)

            # Pre-formatted text with styles
            formatted = FormattedText([("bold", "Title: "), ("", "Content")])
            session.add_response(formatted)
        """
        # Handle FormattedText directly
        if isinstance(content, (FormattedText, list)):
            self._display.formatted(content)
            return

        # Handle markdown
        if markdown:
            self._display.markdown(content)
            return

        # Plain text
        self._display.response(content)

    def add_message(
        self,
        role: Literal["user", "assistant", "thinking", "system"],
        content: str,
    ) -> None:
        """
        Add a styled message to history and print to console.

        Args:
            role: The message role. Must be one of:
                - "user": User input message
                - "assistant": Assistant response
                - "thinking": Thinking/reasoning content
                - "system": System notification
            content: The message content.
        """
        if role == "user":
            prompt_str = self._get_prompt_string()
            self._display.user_input(prompt_str, content)
        elif role == "assistant":
            self._display.response(content)
        elif role == "thinking":
            self._display.thinking(content)
        elif role == "system":
            self._display.system(content)
        else:
            # Unknown role - add as raw text
            self._display.raw(f"{content}\n")

    def add_error(self, content: str) -> None:
        """
        Add an error message with [ERROR] prefix.

        Args:
            content: The error message content.

        Example:
            session.add_error("Failed to connect to server")
            # Displays: [ERROR] Failed to connect to server
        """
        self._display.error(content)

    def add_warning(self, content: str) -> None:
        """
        Add a warning message with [WARN] prefix.

        Args:
            content: The warning message content.

        Example:
            session.add_warning("Rate limit approaching")
            # Displays: [WARN] Rate limit approaching
        """
        self._display.warning(content)

    def add_success(self, content: str) -> None:
        """
        Add a success message with [OK] prefix.

        Args:
            content: The success message content.

        Example:
            session.add_success("Operation completed")
            # Displays: [OK] Operation completed
        """
        self._display.success(content)

    def add_code(self, code: str, language: str = "python") -> None:
        """
        Add syntax-highlighted code.

        Uses Pygments for highlighting. Falls back to plain text if not installed.

        Args:
            code: The source code to highlight.
            language: The programming language (default: "python").

        Example:
            session.add_code("def hello():\\n    return 'world'", "python")
        """
        self._display.code(code, language)

    def add_rich(self, renderable: Any) -> None:
        """
        Add a Rich renderable (Panel, Table, Text, etc.) to history and console.

        Converts the renderable to ANSI-formatted output using Rich's Console.
        Falls back to str() if Rich is not installed.

        Args:
            renderable: Any Rich renderable object (Panel, Table, Text, Tree, etc.).

        Example:
            from rich.panel import Panel
            from rich.table import Table

            # Display a panel
            session.add_rich(Panel("Hello World", title="Greeting"))

            # Display a table
            table = Table(title="Users")
            table.add_column("Name")
            table.add_column("Role")
            table.add_row("Alice", "Admin")
            table.add_row("Bob", "User")
            session.add_rich(table)
        """
        self._display.rich(renderable)

    def clear(self) -> None:
        """
        Clear the display and reset to startup state.

        Clears the terminal screen and history buffer, re-prints the welcome
        message, and returns to prompt mode.
        """
        # Exit fullscreen if active
        with self._fullscreen_lock:
            self._is_fullscreen = False

        # Clear the terminal screen. While the app is running this must
        # go through the renderer — a raw escape write behind its back
        # leaves the renderer's notion of the screen stale and corrupts
        # the next repaint.
        if self.app and self.app.is_running:
            self.app.renderer.clear()
        else:
            # \033[2J clears screen, \033[H homes the cursor.
            print("\033[2J\033[H", end="", flush=True)

        # Clear history buffer and any pending output
        self._display.clear()

        # Re-print welcome message
        self._print_welcome()

        # Refresh UI
        self._invalidate()

    # =========================================================================
    # UI State API
    # =========================================================================

    @property
    def is_fullscreen(self) -> bool:
        """Check if app is in fullscreen mode."""
        with self._fullscreen_lock:
            return self._is_fullscreen

    def switch_to_fullscreen(self) -> None:
        """Switch to fullscreen mode (no-op if fullscreen is disabled)."""
        if not self._fullscreen_enabled:
            return
        with self._fullscreen_lock:
            if not self._is_fullscreen:
                self._is_fullscreen = True
                self._invalidate()

    def switch_to_prompt(self) -> None:
        """Switch back to prompt mode from fullscreen."""
        with self._fullscreen_lock:
            if self._is_fullscreen:
                self._is_fullscreen = False
                # Restore pre-fullscreen expansion state
                if self._pre_fullscreen_expanded is not None:
                    if not self._pre_fullscreen_expanded:
                        self._manager.collapse_all()
                    self._pre_fullscreen_expanded = None
                if self._repaint_on_fullscreen_exit:
                    self._repaint_on_fullscreen_exit = False
                    self._display.drop_pending()
                    self._repaint_console()
                else:
                    self._display.flush_pending()  # Output cached content to console
                self._invalidate()

    def exit(self) -> None:
        """
        Exit the session.

        Call this from a handler to end the session loop.

        Example:
            @session.on_input
            async def handle(text: str):
                if text.strip() == "exit":
                    session.exit()
                    return
                # ... handle other input
        """
        if self.app and self.app.is_running:
            self.app.exit()

    # =========================================================================
    # Handler Registration
    # =========================================================================

    def on_input(self, func: Callable[[str], Any]) -> Callable[[str], Any]:
        """
        Decorator to register an input handler.

        The handler is called when the user submits input. It receives the
        input text as a string and can be sync or async. The handler decides
        whether to use thinking mode by calling start_thinking().

        Warning:
            Handlers run on the event loop. A synchronous handler blocks
            the UI for its entire duration — the screen freezes, spinners
            stop, and Ctrl+C is not processed until it returns. Use an
            async handler for anything that takes time, and wrap blocking
            calls with ``await asyncio.to_thread(...)``.

        Example:
            session = ThinkingPromptSession()

            @session.on_input
            async def handle(text: str):
                if not text.strip():
                    return

                async with session.thinking() as ctx:
                    ctx.append("Processing...\\n")
                    await asyncio.sleep(1)

                session.add_response(f"Echo: {text}")

            await session.run_async()  # No handler arg needed

        Args:
            func: The handler function to register.

        Returns:
            The handler function (unchanged).
        """
        self._input_handler = func
        return func

    # =========================================================================
    # Running the Application
    # =========================================================================

    async def prompt_async(self) -> str:
        """
        Wait for the next user input.

        This should be called in a loop to handle multiple inputs.

        Returns:
            The user's input string.

        Raises:
            EOFError: When Ctrl+D is pressed on an empty input line.
            KeyboardInterrupt: When Ctrl+C is pressed (not during thinking).
        """
        self._pending_input = asyncio.get_running_loop().create_future()
        try:
            return await self._pending_input
        except asyncio.CancelledError as exc:
            raise KeyboardInterrupt() from exc

    async def run_async(
        self,
        handler: Callable[[str], Any] | None = None,
    ) -> None:
        """
        Run the session asynchronously.

        Args:
            handler: Callback for each input. If not provided, uses handler
                     registered with @on_input decorator. The handler decides
                     whether to use thinking mode by calling start_thinking().
                     Sync handlers block the event loop (and the UI) until
                     they return — prefer async handlers for slow work; see
                     on_input() for details.

        Raises:
            ValueError: If no handler is provided and none was registered.

        Example:
            # Option 1: Pass handler directly
            async def handle(text):
                async with session.thinking() as ctx:
                    ctx.append("Working...\\n")
                    await asyncio.sleep(1)

            await session.run_async(handle)

            # Option 2: Use @on_input decorator
            @session.on_input
            async def handle(text):
                ...

            await session.run_async()  # Uses registered handler
        """
        # Print welcome message once at startup
        self._print_welcome()

        # Use provided handler or previously registered one
        effective_handler = handler or self._input_handler
        if effective_handler is None:
            raise ValueError(
                "No handler provided. Either pass a handler to run_async() "
                "or register one with @session.on_input decorator."
            )

        async def input_loop() -> None:
            while True:
                try:
                    text = await self.prompt_async()
                    await self._run_handler(effective_handler, text)
                except (EOFError, KeyboardInterrupt):
                    break
                except asyncio.CancelledError:
                    break

        # Run input loop as background task
        loop_task = asyncio.create_task(input_loop())

        try:
            await self.app.run_async()
        finally:
            loop_task.cancel()
            with suppress(asyncio.CancelledError):
                await loop_task

    async def _run_handler(
        self,
        handler: Callable[[str], None | Coroutine[Any, Any, None]],
        text: str,
    ) -> None:
        """Invoke the input handler with cancellation and cleanup hooks.

        Async handlers run as a tracked ``asyncio.Task`` so the Ctrl+C
        binding can cancel them. On user cancellation, on handler exception,
        or on completion, any thinking boxes the handler left open are
        finished so the UI cannot get stuck in a "thinking" state.

        CancelledError raised from outside the handler (e.g. the input loop
        being cancelled during shutdown) is re-raised so the loop can exit.
        """
        try:
            result = handler(text)
        except Exception as e:
            self._cleanup_after_handler()
            self.add_error(f"Handler error: {e}")
            return

        if not asyncio.iscoroutine(result):
            # Sync handler — already complete. Drop any boxes it left
            # open so the UI can't get stuck in a "thinking" state.
            self._cleanup_after_handler()
            return

        task = asyncio.create_task(result)
        self._current_handler_task = task
        try:
            await task
        except asyncio.CancelledError:
            if self._user_cancelled_handler:
                # Ctrl+C path: swallow and continue the input loop.
                self._cleanup_after_handler()
                return
            # Outer cancellation (e.g. session shutdown) — propagate so
            # the input loop exits.
            self._cleanup_after_handler()
            raise
        except Exception as e:
            self._cleanup_after_handler()
            self.add_error(f"Handler error: {e}")
        else:
            # Handler completed normally — finish any boxes it left open
            # (content is discarded, same as the cancel/error paths).
            self._cleanup_after_handler()
        finally:
            self._current_handler_task = None
            # Always clear the cancel flag for the next invocation. We can't
            # only reset it inside the except CancelledError block: if user
            # code catches CancelledError and returns normally, or if cancel
            # races against natural completion, no exception propagates here
            # and the flag would stay sticky — making the *next* outer
            # cancellation look like a Ctrl+C and silently swallowing it.
            self._user_cancelled_handler = False

    def _cleanup_after_handler(self) -> None:
        """Drop any thinking boxes the handler left open and refresh UI."""
        if self._manager.has_active_boxes:
            self._manager.finish_all()
            self._invalidate()

    def run(self, handler: Callable[[str], Any] | None = None) -> None:
        """
        Run the session synchronously.

        Args:
            handler: Callback for each input. If not provided, uses handler
                     registered with @on_input decorator.

        Raises:
            ValueError: If no handler is provided and none was registered.
        """
        asyncio.run(self.run_async(handler))

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def message(self) -> AnyFormattedText:
        """Get the prompt message."""
        return self._message

    @message.setter
    def message(self, value: AnyFormattedText) -> None:
        """Set the prompt message."""
        self._message = value
        self._invalidate()

    @property
    def status_text(self) -> AnyFormattedText:
        """Get the current status bar text."""
        return self._status_text

    @status_text.setter
    def status_text(self, value: AnyFormattedText) -> None:
        """Set the status bar text (str or FormattedText)."""
        self._status_text = value
        self._invalidate()

    def set_status(self, text: Any) -> None:
        """
        Set the status bar text.

        Accepts plain text, FormattedText, or Rich renderables.
        """
        if _is_rich_renderable(text):
            self._status_text = self._display.to_ansi(text)
        else:
            self._status_text = text
        self._invalidate()

    # =========================================================================
    # Dialog API
    # =========================================================================

    @property
    def _dialogs(self) -> DialogManager:
        """Get or create the dialog manager (lazy initialization)."""
        if self._dialog_manager is None:
            from .dialog import DialogManager
            self._dialog_manager = DialogManager(self)
        return self._dialog_manager

    async def yes_no_dialog(
        self,
        title: str,
        text: str,
        yes_text: str = "Yes",
        no_text: str = "No",
    ) -> bool:
        """
        Show a Yes/No confirmation dialog.

        Args:
            title: Dialog title.
            text: Dialog body text.
            yes_text: Text for Yes button (default: "Yes").
            no_text: Text for No button (default: "No").

        Returns:
            True if Yes was clicked, False if No or Escape.

        Example:
            if await session.yes_no_dialog("Confirm", "Delete this file?"):
                delete_file()
        """
        from .dialog import _YesNoDialog
        dialog = _YesNoDialog(title, text, yes_text, no_text)
        return cast(bool, await self._dialogs.show(dialog))

    async def message_dialog(
        self,
        title: str,
        text: str,
        ok_text: str = "OK",
    ) -> None:
        """
        Show an informational message dialog.

        Args:
            title: Dialog title.
            text: Dialog body text.
            ok_text: Text for OK button (default: "OK").

        Example:
            await session.message_dialog("Info", "Operation completed.")
        """
        from .dialog import _MessageDialog
        dialog = _MessageDialog(title, text, ok_text)
        await self._dialogs.show(dialog)

    async def choice_dialog(
        self,
        title: str,
        text: str,
        choices: Sequence[str],
    ) -> str | None:
        """
        Show a dialog with multiple choice buttons.

        Args:
            title: Dialog title.
            text: Dialog body text.
            choices: List of choice strings (each becomes a button).

        Returns:
            The selected choice string, or None if Escape was pressed.

        Example:
            action = await session.choice_dialog(
                "Select Action",
                "What would you like to do?",
                ["Save", "Discard", "Cancel"],
            )
            if action == "Save":
                save_file()
        """
        from .dialog import _ChoiceDialog
        dialog = _ChoiceDialog(title, text, choices)
        return cast(Optional[str], await self._dialogs.show(dialog))

    async def dropdown_dialog(
        self,
        title: str,
        text: str,
        options: Sequence[str],
        default: str | None = None,
    ) -> str | None:
        """
        Show a dialog with a dropdown/radio list selection.

        Args:
            title: Dialog title.
            text: Dialog body text.
            options: List of options to choose from.
            default: Default selected option (optional).

        Returns:
            The selected option string, or None if cancelled.

        Example:
            theme = await session.dropdown_dialog(
                "Select Theme",
                "Choose a color theme:",
                ["Light", "Dark", "System"],
                default="System",
            )
        """
        from .dialog import _DropdownDialog
        dialog = _DropdownDialog(title, text, options, default)
        return cast(Optional[str], await self._dialogs.show(dialog))

    async def show_dialog(
        self,
        dialog: DialogConfig | BaseDialog,
    ) -> Any:
        """
        Show a custom dialog.

        Args:
            dialog: Either a DialogConfig for simple dialogs,
                   or a BaseDialog subclass for complex dialogs.

        Returns:
            The result value set by the dialog.

        Example with DialogConfig:
            from thinking_prompt.dialog import DialogConfig, ButtonConfig

            config = DialogConfig(
                title="Custom",
                body="Choose an option:",
                buttons=[
                    ButtonConfig(text="Option A", result="a"),
                    ButtonConfig(text="Option B", result="b"),
                ],
            )
            result = await session.show_dialog(config)

        Example with BaseDialog subclass:
            from thinking_prompt.dialog import BaseDialog

            class MyDialog(BaseDialog):
                title = "My Dialog"

                def build_body(self):
                    return Label("Custom content")

                def get_buttons(self):
                    return [("OK", lambda: self.set_result(True))]

            result = await session.show_dialog(MyDialog())
        """
        return await self._dialogs.show(dialog)

    async def show_settings_dialog(
        self,
        title: str,
        items: list[SettingsItem],
        can_cancel: bool = True,
        styles: dict | None = None,
        width: int | None = 60,
        top: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any] | None:
        """
        Show a settings dialog and return changed values.

        Args:
            title: Dialog title.
            items: List of SettingsItem objects defining the form.
            can_cancel: If True (default), shows Save/Cancel buttons.
                       If False, shows only Done button.
            styles: Optional style overrides.
            width: Dialog width control:
                   - None or 0: auto-size to content
                   - positive int: minimum width (default 60)
                   - -1: maximum width (stretch to fill)
            top: Vertical position:
                   - None: center (default)
                   - 0 or positive: offset from top
                   - negative: offset from bottom (e.g., -1 = 1 row from bottom)
            height: Fixed total dialog height. When set, the dialog is
                    allocated the full height in one render frame instead
                    of growing line-by-line. Body overflow scrolls.
                    When None (default), the dialog sizes to its content.

        Returns:
            Dictionary of changed values if saved, or None if cancelled.
            An empty dict {} means no values were changed.

        Example:
            from thinking_prompt import DropdownItem, CheckboxItem

            result = await session.show_settings_dialog(
                title="Settings",
                items=[
                    DropdownItem(key="model", label="Model",
                                options=["gpt-4", "gpt-3.5"], default="gpt-4"),
                    CheckboxItem(key="stream", label="Stream Output", default=True),
                ],
            )
            if result is not None:
                for key, value in result.items():
                    update_setting(key, value)
        """
        from .settings_dialog import SettingsDialog
        dialog = SettingsDialog(
            title, items, can_cancel, styles, width, top, height
        )
        return cast(
            "dict[str, Any] | None", await self._dialogs.show(dialog)
        )
