"""
ThinkingPromptSession - A chat-like interface with thinking box.

This module provides a PromptSession-like interface that adds a thinking box
above the input. The thinking box appears when processing user input and
can be expanded to show all of its content.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from collections.abc import AsyncIterator, Coroutine, Sequence
from contextlib import asynccontextmanager, suppress
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Optional,
    TypeVar,
    cast,
)

if TYPE_CHECKING:
    from .dialog import Dialog, DialogManager
    from .thinking_box import ThinkingBox
    from .types import ContentCallback, ContentFormat, InputHandler, Overflow

from prompt_toolkit.application import Application, get_app, run_in_terminal
from prompt_toolkit.application.current import get_app_session
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.enums import DEFAULT_BUFFER, EditingMode
from prompt_toolkit.filters import Condition, has_focus, is_done
from prompt_toolkit.formatted_text import (
    AnyFormattedText,
    FormattedText,
    fragment_list_to_text,
    to_formatted_text,
)
from prompt_toolkit.history import History, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.layout import AnyContainer, ConditionalContainer, DynamicContainer, Window
from prompt_toolkit.layout.controls import FormattedTextControl, UIContent, UIControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.output import ColorDepth, Output
from prompt_toolkit.styles import DynamicStyle

from ._text import format_exception_detail
from .app_info import AppInfo
from .display import Display
from .frames import POLL_INTERVAL, FrameScheduler
from .layout import create_layout
from .manager import ThinkingBoxManager
from .resize import ShrinkRepaint
from .rich_utils import _is_rich_renderable
from .spinner import Spinner
from .styles import ThinkingPromptStyles, resolve_theme
from .types import InputWhileBusy, Placement, check_input_while_busy, check_placement

logger = logging.getLogger(__name__)

# on_input() returns the handler it registers with its own type.
_HandlerT = TypeVar("_HandlerT", bound="InputHandler")
_T = TypeVar("_T")


class _RoomControl(UIControl):
    """Blank content whose menu position is its top-left corner, which a
    float attached to the window can use as its anchor."""

    def __init__(self) -> None:
        # (render_counter, rows) of the last draw: whether the room got its
        # rows in this render.
        self.drawn: tuple[int, int] | None = None

    def create_content(self, width: int, height: int) -> UIContent:
        self.drawn = (get_app().render_counter, height)
        # The first line holds a space: an empty one maps no position to the screen.
        return UIContent(
            get_line=lambda i: [("", " ")] if i == 0 else [],
            line_count=height,
            menu_position=Point(x=0, y=0),
        )


class ThinkingPromptSession:
    """
    A chat-like prompt session with a thinking box.

    This class provides a prompt interface similar to PromptSession but with
    additional features:
    - A thinking box that appears above the input during processing
    - Expand/collapse of thinking boxes (Ctrl+T by default)

    The handler decides whether to show a thinking box: start one with
    start_thinking() or the thinking() context manager, and write to it.

    Attributes:
        app: The prompt_toolkit Application the session runs, for what the
            session doesn't cover (e.g. app.invalidate(), or key bindings
            through app.key_bindings). Its layout is the session's own.

    Example:
        app_info = AppInfo(name="MyApp", version="1.0.0")
        session = ThinkingPromptSession(app_info=app_info)

        @session.on_input
        async def handle(user_input: str):
            if not user_input.strip():
                return

            async with session.thinking() as box:
                box.append("Processing...\\n")
                await asyncio.sleep(1)
                box.append("Done!\\n")

            session.add_response(f"Echo: {user_input}")

        await session.run_async()
    """

    # Status hint shown when Enter is refused because nobody awaits input.
    _BUSY_STATUS = "Busy — press Ctrl+C to cancel"
    # Status hint shown when Ctrl+C at an idle prompt leaves live tasks' boxes.
    _BACKGROUND_STATUS = "Background work is running — Ctrl+D exits"

    def __init__(
        self,
        message: AnyFormattedText = ">>> ",
        *,
        app_info: AppInfo | None = None,
        theme: str | ThinkingPromptStyles | None = None,
        history: History | None = None,
        completer: Completer | None = None,
        complete_while_typing: bool = False,
        completions_menu_height: int = 5,
        editing_mode: EditingMode = EditingMode.EMACS,
        enable_status_bar: bool = True,
        status_text: AnyFormattedText = "Ctrl+C: cancel | Ctrl+D: exit",
        expand_key: str = "c-t",
        thinking_max_lines: int = 15,
        thinking_title: str = "Thinking",
        thinking_border: bool = True,
        spinner: Spinner | None = Spinner.DOTS,
        spinner_position: Literal["before", "after"] = "before",
        echo_input: bool = True,
        thinking_echo: bool = True,
        transcript_limit: int | None = None,
        dialog_placement: Placement = "box",
        input_while_busy: InputWhileBusy = "refuse",
    ) -> None:
        """
        Initialize the ThinkingPromptSession.

        Args:
            message: The prompt message to display. Every other argument
                is keyword-only.
            app_info: The banner printed at startup (name, version, welcome
                message). None (default): no banner.
            theme: Theme name ('dark', 'light', 'mono', 'terminal', 'auto') or
                   ThinkingPromptStyles instance. Default: 'dark'.
            history: History object for input history.
            completer: Completer for input autocompletion.
            complete_while_typing: Show completions automatically while typing.
            completions_menu_height: Maximum height of completions dropdown menu.
            editing_mode: Editing mode (EMACS or VI).
            enable_status_bar: Whether to show status bar.
            status_text: Text to display in status bar.
            expand_key: Expands/collapses thinking boxes.
                Default: "c-t" (Ctrl+T).
            thinking_max_lines: The rows a box shows collapsed, below its title,
                unless the box sets its own ``max_lines``. 0: its title line
                only, a processing indicator.
            thinking_title: Header title of boxes started without one.
                "" for none.
            thinking_border: Whether a box's header line has its border
                ("── ⠋ Thinking ───") or is just the spinner and the title
                ("⠋ Thinking"), unless the box says. Default: True.
            spinner: The thinking header's spinner: a preset such as
                ``Spinner.LINE``, your own ``Spinner(frames, interval)``,
                or None for none. Default: ``Spinner.DOTS``.
            spinner_position: The spinner "before" (default) or "after" the
                title.
            echo_input: Whether to echo user input to console before thinking.
            thinking_echo: Whether a finished box's text is printed to the
                console (and kept for repaints) or dropped, when its finish
                call doesn't say. Default: True.
            transcript_limit: Max transcript entries kept for repaints;
                             oldest trimmed. None = unbounded.
            dialog_placement: How dialogs are drawn unless they say otherwise:
                "box" (default) floats a framed dialog over the session;
                "inline" draws rows between the prompt and the status bar.
            input_while_busy: What Enter does while nobody is waiting in
                prompt_async() (a query runs): "refuse" (default) keeps
                the line in the prompt and says the session is busy;
                "queue" takes the line, shows it under the prompt, and
                prompt_async() returns it next. Up on an empty prompt
                takes the newest queued line back to edit.

        Raises:
            ValueError: If thinking_max_lines is less than 0, or theme= names
                       an unknown theme, or if dialog_placement isn't 'box'
                       or 'inline', or if input_while_busy isn't 'refuse' or
                       'queue'.
        """
        if thinking_max_lines < 0:
            raise ValueError("thinking_max_lines must be at least 0")

        self._message = message
        self._app_info = app_info
        self._thinking_title = thinking_title
        check_placement(dialog_placement)
        self._dialog_placement: Placement = dialog_placement
        check_input_while_busy(input_while_busy)
        self._input_while_busy: InputWhileBusy = input_while_busy
        # Lines Enter took while nobody waited for input ("queue"), oldest first.
        self._queued: deque[str] = deque()

        # A fresh instance per session: a shared one would let a tweak to
        # one session's styles restyle every other session.
        self._styles = resolve_theme(theme) if theme is not None else ThinkingPromptStyles()

        # NO_COLOR is read once at construction (no-color.org: non-empty).
        self._no_color = bool(os.environ.get("NO_COLOR"))

        self._thinking_max_lines = thinking_max_lines
        self._enable_status_bar = enable_status_bar
        self._status_text = status_text
        # A status hint ("Busy", "Background work") replaces the status
        # until it's cleared, and the status it replaced comes back (see
        # _show_hint / _clear_hint / _status_now).
        self._hint: str | None = None
        self._status_under_hint: AnyFormattedText = None
        self._editing_mode = editing_mode
        self._echo_input = echo_input
        self._completer = completer
        self._complete_while_typing = complete_while_typing
        self._completions_menu_height = completions_menu_height

        # Convert styles dataclass to prompt_toolkit Style
        self._style = self._styles.to_style()

        # Display handles all output to console and transcript
        self._display = Display(
            get_style=lambda: self._style,
            thinking_styles=self._styles,
            get_color_depth=self._effective_color_depth,
            transcript_limit=transcript_limit,
            get_width=lambda: self.app.output.get_size().columns,
        )

        self._expand_key = expand_key

        # Redraws on demand: writes redraw now, animations ask for their
        # next frame; nothing redraws on a timer (see _create_application).
        self._frames = FrameScheduler(lambda: self.app.invalidate())
        # A repaint once the terminal stops shrinking (see resize.py).
        self._shrinks = ShrinkRepaint(self._repaint_after_shrink)

        # Thinking box manager: the boxes on screen, and their echo when
        # they end. expand_key flows through to each box so the truncation
        # hint matches the key bound below in _create_key_bindings.
        self._manager = ThinkingBoxManager(
            self._display,
            default_max_lines=thinking_max_lines,
            expand_key=self._expand_key,
            frames=self._frames,
            thinking_echo=thinking_echo,
            spinner=spinner,
            spinner_position=spinner_position,
            border=thinking_border,
        )

        # Input history (for up/down arrow)
        self._input_history = history or InMemoryHistory()

        # Input handler callback (can be set via @on_input decorator or run_async)
        self._input_handler: InputHandler | None = None

        # Pending input future for async handling
        self._pending_input: asyncio.Future[str] | None = None

        # The foreground query (a run_async handler's, or query()'s): the
        # task Ctrl+C cancels.
        self._foreground: asyncio.Task[Any] | None = None
        # The task running run_async() (None otherwise). Its boxes count as
        # nobody's: it's busy running the app, so the session ends them.
        self._app_task: asyncio.Task[Any] | None = None
        # The task running the Application while `async with session:` (or
        # run_async()) runs it; None outside.
        self._app_run: asyncio.Task[Any] | None = None
        # Set to True by the Ctrl+C binding when it cancels the handler task.
        # _run_handler reads this to distinguish a user-initiated cancel
        # (swallow CancelledError, continue the input loop) from an outer
        # cancellation (re-raise to let the input loop exit).
        self._user_cancelled_handler: bool = False
        # Boxes were cancelled during a Ctrl+C of the handler: one
        # "Operation cancelled..." follows them once the handler ends.
        self._cancel_line_pending: bool = False

        # Dialog manager (lazy initialization)
        self._dialog_manager: DialogManager | None = None
        # Shown in the layout's inline-dialog slot while no inline dialog is open.
        self._no_inline_dialog = Window(height=0)
        # Blank rows as tall as an open box dialog: see _inline_dialog_content.
        # Its control reports a menu position at its top-left: the box floats
        # from there (a window not in focus records no cursor position).
        self._room_control = _RoomControl()
        self._box_dialog_room = Window(self._room_control, height=self._box_dialog_rows)

        # Create components
        self._default_buffer = self._create_default_buffer()
        self.app = self._create_application()

    def _get_prompt_string(self) -> str:
        """Get the prompt's visible text (any AnyFormattedText form, e.g.
        HTML or ANSI objects, callables, fragment lists)."""
        return fragment_list_to_text(to_formatted_text(self._message))

    def _input_wanted(self) -> bool:
        """True when submitted input would reach someone: a task is waiting
        in prompt_async() (the input loop, or a query asking a follow-up).

        False while a query runs without asking, and in the gap between one
        line resolving the pending future and the loop's next
        prompt_async(): a second line arriving in the same read (typed
        ahead during a blocking handler, say) lands there.
        """
        pending = self._pending_input
        return pending is not None and not pending.done()

    def _record_input(self, text: str) -> None:
        """A line becomes input: it goes into the input history (↑) and
        is echoed."""
        if text.strip():
            self._input_history.append_string(text)
            if self._echo_input:
                self._display.user_input(self._get_prompt_string(), text)

    def _busy_enter(self) -> None:
        """Enter while nobody waits for input: queue the line, or refuse it
        (it stays in the prompt, and the status bar says so)."""
        if self._input_while_busy == "queue":
            text = self._default_buffer.text
            if text.strip():
                self._queued.append(text)
                self._default_buffer.reset()
                self._invalidate()
            return
        self._show_hint(self._BUSY_STATUS)

    def _show_hint(self, hint: str) -> None:
        """Show a status hint, keeping the status it replaces."""
        if self._hint is None or self._status_text != self._hint:
            self._status_under_hint = self._status_text
        self._hint = hint
        self.status_text = hint

    def _clear_hint(self) -> None:
        """Restore the status the hint replaced — unless something set a new
        status meanwhile (e.g. the handler reporting its result)."""
        if self._hint is None:
            return
        if self._status_text == self._hint:
            self.status_text = self._status_under_hint
        self._hint = None
        self._status_under_hint = None

    def _status_now(self) -> AnyFormattedText:
        """The status to show. The background hint lasts only while a box
        is open: once the last one ends, the status it replaced is back."""
        if self._hint == self._BACKGROUND_STATUS and not self._manager.has_active_boxes:
            self._clear_hint()
        return self._status_text

    def _create_default_buffer(self) -> Buffer:
        """Create the main input buffer."""

        def accept_handler(buff: Buffer) -> bool:
            """Handle input acceptance."""
            # Backstop for the check in the Enter binding (accept_input),
            # which refuses before prompt_toolkit touches the buffer. Note
            # the return value means *keep_text*: True keeps the draft.
            if not self._input_wanted():
                self._busy_enter()
                return True
            # Input is accepted: a status hint no longer applies.
            self._clear_hint()

            text = buff.document.text

            self._record_input(text)

            # Signal that input is ready - handler decides whether to use thinking mode
            assert self._pending_input is not None  # checked by _input_wanted()
            self._pending_input.set_result(text)

            # Clear buffer for next input. Resetting here (rather than
            # returning False) empties it before validate_and_handle's own
            # append_to_history, which would otherwise record it twice.
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
        return create_layout(
            default_buffer=self._default_buffer,
            message=lambda: self._polled(self._message),
            thinking_max_lines=self._thinking_max_lines,
            get_status_text=lambda: self._polled(self._status_now()),
            is_status_bar_enabled=lambda: self._enable_status_bar,
            thinking_manager=self._manager,
            completions_menu_height=self._completions_menu_height,
            inline_dialog=DynamicContainer(self._inline_dialog_content),
            queued=self._queued_rows(),
        )

    def _queued_rows(self) -> AnyContainer:
        """The queued lines, one row each, under the input area."""
        def text() -> FormattedText:
            rows = "\n".join(f"  queued: {line}" for line in self._queued)
            return FormattedText([("class:queued-input", rows)])

        return ConditionalContainer(
            Window(
                FormattedTextControl(text),
                height=lambda: Dimension.exact(len(self._queued)),
                wrap_lines=False,
            ),
            # Left out of the app's last frame: lines still queued at exit
            # are dropped, so the scrollback shouldn't keep them.
            filter=Condition(lambda: bool(self._queued)) & ~is_done,
        )

    def _polled(self, text: AnyFormattedText) -> AnyFormattedText:
        """Text about to be drawn. A callable is re-read every
        POLL_INTERVAL while it's drawn: nothing says when its text changes."""
        if callable(text):
            self._frames.redraw_in(POLL_INTERVAL)
        return text

    def _create_application(self) -> Application:
        """Create the Application object."""

        # Key bindings
        kb = self._create_key_bindings()

        app: Application = Application(
            layout=self._create_session_layout(),
            style=DynamicStyle(lambda: self._style),
            key_bindings=kb,
            editing_mode=self._editing_mode,
            # No refresh_interval: redrawn when something changes or an
            # animation asks (FrameScheduler), so an idle prompt costs
            # nothing. Bursts of writes are capped at 30 redraws a second.
            min_redraw_interval=1 / 30,
            color_depth=self._effective_color_depth,
        )
        # Every resize redraws: each draw tells _shrinks the terminal's size.
        app.before_render += lambda sender: self._shrinks.seen(sender.output.get_size())
        return app

    def _create_key_bindings(self) -> KeyBindings:
        """Create key bindings for the session."""
        kb = KeyBindings()

        # Cancel/interrupt — cancel the running handler, or finish boxes.
        # Falls through to exit (cancelling pending input) when no handler
        # was running and no boxes were active. A live pending input
        # future does NOT count as in-flight work: it merely means the
        # prompt is waiting for input, which is the idle state.
        @kb.add("c-c")
        def cancel(event: KeyPressEvent) -> None:
            """Cancel current operation or exit."""
            # Snapshot state BEFORE we mutate anything. Otherwise the final
            # idle check below would re-read state we just cleared (e.g.
            # has_active_boxes after ending the boxes) and incorrectly conclude
            # there was nothing to cancel, triggering app.exit().
            handler_running = (
                self._foreground is not None
                and not self._foreground.done()
            )
            had_active_boxes = self._manager.has_active_boxes
            had_pending_input = (
                self._pending_input is not None
                and not self._pending_input.done()
            )

            if handler_running:
                # Mark before cancel so _run_handler treats this as a user
                # cancellation and does not re-raise CancelledError.
                # Its boxes are finished as it unwinds (and by
                # _run_handler's cleanup); a background task's live box
                # keeps going.
                self._user_cancelled_handler = True
                assert self._foreground is not None
                self._foreground.cancel()
            elif had_active_boxes:
                # Idle prompt: end the boxes nobody else will end (their task
                # ended, no known owner, or the app's own task opened them).
                # A live task's box is that task's to end.
                ended = self._manager.finish_owned_by(self._app_task)
                self._announce_cancel(bool(ended))
                if self._manager.has_active_boxes:
                    # Only live tasks' boxes are left: their work is theirs to
                    # stop, so don't exit, now or at the next Ctrl+C;
                    # say how to.
                    self._show_hint(self._BACKGROUND_STATUS)

            if not handler_running and not had_active_boxes:
                # No handler and no boxes — the session is idle, so Ctrl+C
                # means "exit". At an idle prompt the pending-input future
                # is always live (prompt_async is awaiting it), so it must
                # not count as in-flight work: treating it as such used to
                # kill the input loop while leaving the app running, after
                # which typed input was echoed but silently dropped.
                # Cancelling it makes direct prompt_async() callers observe
                # KeyboardInterrupt; app.exit() ends run_async()'s own loop.
                if had_pending_input:
                    assert self._pending_input is not None
                    self._pending_input.cancel()
                event.app.exit()
            # Otherwise the pending input (if any) is left alone: cancelling
            # it would end the input loop while the app — which is not
            # exiting — keeps running, a zombie session.

        # Exit (EOF) — only on an empty input line, matching readline
        # semantics. With text in the buffer this binding is inactive and
        # prompt_toolkit's default emacs binding (delete-char) handles the
        # key, so a typed draft is never destroyed by a stray Ctrl+D. The
        # prompt must also have focus: in a dialog's text field Ctrl+D is
        # delete-char, whatever the (hidden) main buffer holds.
        @kb.add(
            "c-d",
            filter=has_focus(DEFAULT_BUFFER)
            & Condition(lambda: not self._default_buffer.text),
        )
        def exit_app(event: KeyPressEvent) -> None:
            """Exit the application."""
            # A running query is cancelled, as when the app stops: if it
            # was asking a follow-up, its prompt ends with it and query()
            # returns None. Otherwise a waiting prompt_async() gets the
            # documented EOFError instead of hanging forever.
            foreground = self._foreground
            if foreground is not None and not foreground.done():
                foreground.cancel()
            elif self._pending_input is not None and not self._pending_input.done():
                self._pending_input.set_exception(EOFError())
            event.app.exit()

        # Enter to submit (when not thinking)
        @kb.add("enter", filter=has_focus(DEFAULT_BUFFER))
        def accept_input(event: KeyPressEvent) -> None:
            """Accept input, or refuse it when nobody is waiting for it."""
            # Refused input stays in the buffer, untouched: if we accepted,
            # the text would be echoed and the buffer cleared, but nobody
            # would pick it up — it would just vanish. The check runs here,
            # before validate_and_handle(), so prompt_toolkit neither
            # clears the draft nor records it in the input history.
            if not self._input_wanted():
                self._busy_enter()
                return
            self._default_buffer.validate_and_handle()

        @kb.add(
            "up",
            filter=has_focus(DEFAULT_BUFFER)
            & Condition(lambda: bool(self._queued) and not self._default_buffer.text),
        )
        def recall_queued(event: KeyPressEvent) -> None:
            """Up on an empty prompt: the newest queued line, back to edit."""
            text = self._queued.pop()
            self._default_buffer.document = Document(text, len(text))
            self._invalidate()

        # Expand/collapse — toggle all via manager
        @kb.add(self._expand_key, filter=Condition(self._manager.can_toggle))
        def toggle_expand(event: KeyPressEvent) -> None:
            self._manager.toggle_all()
            self._invalidate()

        return kb

    def _effective_color_depth(self) -> ColorDepth | None:
        """NO_COLOR (env, at construction) wins; else the theme's hint."""
        if self._no_color:
            return ColorDepth.DEPTH_1_BIT
        return self._styles.color_depth

    @property
    def styles(self) -> ThinkingPromptStyles:
        """The theme in use: the instance passed as ``theme=`` (not a copy),
        or a built-in one. A field changed on it shows once it's passed to
        set_theme() again; dataclasses.replace() makes a tweaked copy."""
        return self._styles

    def set_theme(
        self, theme: str | ThinkingPromptStyles, repaint: bool = False
    ) -> None:
        """Switch the active theme at runtime.

        The live UI (prompt, thinking boxes, dialogs) re-renders in the
        new theme on the next paint. Content already printed to the
        terminal (scrollback) keeps its original colors — only the
        Display's ``get_style`` callable and the Application's
        ``DynamicStyle`` are re-read; scrollback lines already written to
        the terminal are not retroactively recolored, unless
        ``repaint=True`` is passed.

        Args:
            theme: Theme name ('dark', 'light', 'mono', 'terminal', 'auto')
                or a ThinkingPromptStyles instance.
            repaint: If True, clear the screen and scrollback and re-print
                the transcript in the new theme. Markdown and code re-render
                from source; rich/raw ANSI keeps its original colors.
                Terminals that do not support scrollback erase (CSI 3J)
                keep old content above the viewport; the visible screen
                still repaints fully.

        Raises:
            ValueError: For unknown theme names.
        """
        resolved = resolve_theme(theme)
        self._styles = resolved
        self._style = resolved.to_style()
        self._display.set_theme(resolved)
        if repaint:
            self._repaint_console()
        self._invalidate()

    def _repaint_console(self) -> None:
        """Clear screen + scrollback and print the transcript, as it is now,
        again. While the app runs that's one run_in_terminal job (the UI
        erased and redrawn once), queued in order with the prints
        print_formatted_text queues: one already queued prints before the
        clear, a later one after the transcript, and two repaints in a row
        print it once."""
        contents = self._display.printed_contents()

        def repaint(output: Output) -> None:
            output.erase_screen()
            output.cursor_goto(0, 0)
            # Scrollback erase isn't part of Output's interface: CSI 3J.
            output.write_raw("\x1b[3J")
            self._display.print_now(output, contents)
            output.flush()

        app = self.app
        if app and app.is_running and app.loop is not None:
            app.loop.call_soon_threadsafe(lambda: run_in_terminal(lambda: repaint(app.output)))
        else:
            repaint(get_app_session().output)

    def _repaint_after_shrink(self) -> None:
        """Repaint once the terminal stopped shrinking, which left rows of
        the live UI behind (see resize.py)."""
        if self.app and self.app.is_running:
            self._repaint_console()

    def _invalidate(self) -> None:
        """Trigger a UI refresh."""
        if self.app and self.app.is_running:
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
        content_callback: ContentCallback | None = None,
        *,
        title: str | None = None,
        border: bool | None = None,
        order: int = 0,
        max_lines: int | None = None,
        content_format: ContentFormat = "plain",
        overflow: Overflow = "tail",
    ) -> ThinkingBox:
        """
        Start a thinking box and return it.

        Write to the box to show text in it. To show text you already hold,
        pass ``content_callback`` instead: the box re-reads it while it's
        drawn (every 0.1 s), and can be read but not written to. The
        callback must be thread-safe if the text changes in another thread.

        Args:
            content_callback: Returns the text to show. If None, the box
                holds its own text, which you write.
            title: Title on the box's header line (default: the session's
                ``thinking_title``).
            border: False: the header line is just the spinner and the
                title, with no line (default: the session's
                ``thinking_border``).
            order: Sort key for multiple boxes (higher = closer to prompt).
            max_lines: Max collapsed lines (overrides session default). 0:
                the title line only, a processing indicator: its text
                shows expanded (Ctrl+T) and isn't echoed.
            content_format: Format for rendering ("plain" or "ansi").
            overflow: Which end of content that overflows the box stays
                visible — in the box and in the echo when it finishes:
                "tail" (newest lines, default) or "head" (first lines,
                e.g. for a task list).

        Returns:
            The ThinkingBox: write to it, retitle it, and finish it. It
            belongs to the calling task: a box that task leaves open is
            ended by the session (see the README's "When a Box Ends").

        Raises:
            ValueError: If max_lines is less than 0.

        Example:
            box = session.start_thinking(title="Processing")
            box.append("Processing...\\n")
            await asyncio.sleep(0.5)
            box.set_title("Finishing")
            box.append("Done!\\n")
            box.finish()
        """
        # 0: the title line only; 1: the newest row, no hint.
        if max_lines is not None and max_lines < 0:
            raise ValueError(f"max_lines must be at least 0 (or None), got {max_lines!r}")
        return self._manager.create_box(
            content_callback,
            title=title if title is not None else self._thinking_title,
            border=border,
            order=order,
            max_lines=max_lines,
            content_format=content_format,
            overflow=overflow,
        )

    def _announce_cancel(self, ended: bool) -> None:
        """Say "Operation cancelled..." after the boxes a cancel ended.

        While Ctrl+C is cancelling the handler, the line waits until the
        handler is done, so one line follows every box that cancel ends
        (see _run_handler). When nothing ended, there's nothing to say.
        """
        if not ended:
            return
        if self._user_cancelled_handler:
            self._cancel_line_pending = True
        else:
            self._display.system("Operation cancelled...")
            self._invalidate()

    @property
    def is_thinking(self) -> bool:
        """True while any thinking box is open, a background task's too (so
        it can be True at an idle prompt)."""
        return self._manager.has_active_boxes

    @asynccontextmanager
    async def thinking(
        self,
        *,
        title: str | None = None,
        border: bool | None = None,
        content_format: ContentFormat = "plain",
        echo: bool | None = None,
        order: int = 0,
        max_lines: int | None = None,
        overflow: Overflow = "tail",
    ) -> AsyncIterator[ThinkingBox]:
        """
        Context manager for thinking operations: yields a ThinkingBox and
        finishes it when the block ends.

        Args:
            title: Optional title for the thinking separator.
            border: False: the header line is just the spinner and the
                title (default: the session's ``thinking_border``).
            content_format: Format for rendering ("plain" or "ansi").
            echo: If True, print the box's text to the console
                (and keep it for repaints) when the block ends; if False,
                drop it. None (default) follows the session's
                thinking_echo.
            order: Sort key for multiple boxes (higher = closer to prompt).
            max_lines: Max collapsed lines (overrides session default); 0:
                the title line only.
            overflow: Which end of overflowing content stays visible, in
                the box and the finish echo: "tail" (newest lines, default)
                or "head" (first lines).

        Yields:
            ThinkingBox: the box, to write to and retitle.

        Raises:
            ValueError: If max_lines is less than 0 (before the block runs).

        Example:
            async with session.thinking(title="Processing") as box:
                box.append("Working...\\n")
                await asyncio.sleep(1)
                box.set_title("Finishing")
                box.append("Done!\\n")

            # Thinking is automatically finished when exiting the context

        Example with Rich-styled lines:
            async with session.thinking() as box:
                box.append_rich("[dim]  Step 1: Load data[/dim]\\n")
                box.append_rich("[dim]  Step 2: Process[/dim]\\n")

                await do_step_1()
                box.set_line_rich(0, "[green]✓ Step 1: Load data[/green]")
                box.set_line_rich(1, "[bold]⟳ Step 2: Processing...[/bold]")

                await do_step_2()
                box.set_line_rich(1, "[green]✓ Step 2: Process[/green]")

        Note:
            The box's content is kept however the block ends. If the block
            is cancelled (e.g. Ctrl+C), "Operation cancelled..." follows the
            content; if it raises, the exception propagates after the box
            is finished.
        """
        box = self.start_thinking(
            title=title,
            border=border,
            content_format=content_format,
            order=order,
            max_lines=max_lines,
            overflow=overflow,
        )
        try:
            yield box
        except asyncio.CancelledError:
            ended = self._manager.finish(box, echo=echo)
            self._announce_cancel(ended)
            raise
        except BaseException:
            box.finish(echo=echo)
            raise
        else:
            box.finish(echo=echo)

    # =========================================================================
    # Output API
    # =========================================================================

    def add_response(
        self,
        content: str | FormattedText,
        *,
        markdown: bool = False,
    ) -> None:
        """
        Add a response to the console and transcript.

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

    def add_system(self, content: str) -> None:
        """
        Print a system message: a note from the app rather than an answer
        (e.g. "Connecting..."), in the system style.

        Args:
            content: The message.

        Example:
            session.add_system("Connecting to server...")
        """
        self._display.system(content)

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
        Add a Rich renderable (Panel, Table, Text, etc.) to the console and transcript.

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

        Clears the terminal screen and transcript, and re-prints the
        welcome message.
        """
        # Clear the terminal screen. While the app is running this must
        # go through the renderer — a raw escape write behind its back
        # leaves the renderer's notion of the screen stale and corrupts
        # the next repaint.
        if self.app and self.app.is_running:
            self.app.renderer.clear()
        else:
            # \033[2J clears screen, \033[H homes the cursor.
            print("\033[2J\033[H", end="", flush=True)

        # Clear the transcript and any pending output
        self._display.clear()

        # Re-print welcome message
        self._print_welcome()

        # Refresh UI
        self._invalidate()

    # =========================================================================
    # Exiting
    # =========================================================================

    def exit(self) -> None:
        """
        Exit the session.

        Call this from a handler to end the session loop. Open boxes are
        handled as on any exit (see run_async()).

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

    def on_input(self, func: _HandlerT) -> _HandlerT:
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

                async with session.thinking() as box:
                    box.append("Processing...\\n")
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

    async def __aenter__(self) -> ThinkingPromptSession:
        """Run the session until the block ends: print the welcome, then
        start the Application. Inputs are read with prompt_async(), and
        query() runs one input's work.

        Raises:
            RuntimeError: If the session is already running.
        """
        if self._app_run is not None:
            raise RuntimeError("The session is already running")
        self._print_welcome()
        self._app_task = asyncio.current_task()
        started = asyncio.Event()
        run = asyncio.ensure_future(self.app.run_async(pre_run=started.set))
        run.add_done_callback(self._app_stopped)
        self._app_run = run
        waiting = asyncio.ensure_future(started.wait())
        try:
            await asyncio.wait({waiting, run}, return_when=asyncio.FIRST_COMPLETED)
        except BaseException:
            run.cancel()
            self._app_run = None
            self._app_task = None
            raise
        finally:
            waiting.cancel()
        if not started.is_set():
            # The app ended before it started (e.g. no terminal): its error.
            self._app_run = None
            self._app_task = None
            run.result()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Stop the app, then end the boxes as any exit does."""
        run = self._app_run
        if run is None:
            return
        try:
            self._exit_app()
            await asyncio.wait({run})
        finally:
            self._app_run = None
            self._queued.clear()
            # The UI is gone. End the boxes nobody else will end, echoing
            # them below its last frame; a live task's box is left to it,
            # and ended when that task ends if the task doesn't end it.
            self._manager.finish_owned_by(self._app_task)
            self._manager.finish_when_owners_end()
            self._app_task = None
            self._frames.cancel()
            self._shrinks.cancel()
        error = None if run.cancelled() else run.exception()
        if error is not None and exc_info[1] is None:
            raise error

    def _app_stopped(self, run: asyncio.Future[Any]) -> None:
        """The app has stopped (Ctrl+D, exit(), the block ending): the
        foreground query is cancelled, and a waiting prompt_async() raises
        EOFError."""
        foreground = self._foreground
        if foreground is not None and not foreground.done():
            foreground.cancel()
        pending = self._pending_input
        if pending is not None and not pending.done():
            pending.set_exception(EOFError())

    async def prompt_async(self) -> str:
        """
        Wait for the next input line.

        Call it inside ``async with session:`` (a handler of run_async() is
        inside too, e.g. to ask a follow-up). The app runs for the whole
        block; this only waits for the next line it accepts. Lines queued
        while busy (input_while_busy="queue") come first, oldest first, each
        echoed as it's returned.

        Returns:
            The input line.

        Raises:
            EOFError: On Ctrl+D at an empty prompt, and on any call once the
                app has stopped (Ctrl+D, exit()).
            KeyboardInterrupt: On Ctrl+C at an idle prompt (no query
                running, no box open); the app exits.
            RuntimeError: Outside ``async with session:``, or while another
                task is already waiting here.
        """
        run = self._app_run
        if run is None:
            raise RuntimeError(
                "prompt_async() reads the input of a running session: "
                "call it inside `async with session:`"
            )
        if run.done() or self.app.is_done:
            # Stopped, or told to stop (exit() takes the app a few loop
            # turns): queued lines don't run after a quit.
            raise EOFError
        pending = self._pending_input
        if pending is not None and not pending.done():
            raise RuntimeError("Another task is already waiting in prompt_async()")
        if self._queued:
            text = self._queued.popleft()
            self._clear_hint()
            self._record_input(text)
            self._invalidate()
            return text
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending_input = future
        # Input is wanted again: a status hint no longer applies.
        self._clear_hint()
        try:
            # wait() rather than await: this task's own cancellation stays a
            # cancellation, and only the future's (Ctrl+C) is an interrupt.
            await asyncio.wait({future})
        except asyncio.CancelledError:
            future.cancel()
            raise
        if future.cancelled():
            raise KeyboardInterrupt
        return future.result()  # EOFError after Ctrl+D or the app stopping

    async def query(self, coro: Coroutine[Any, Any, _T]) -> _T | None:
        """
        Run one input's work as the foreground query: the one Ctrl+C cancels.

        The coroutine runs as a task of its own, which owns the boxes it
        opens: boxes it leaves open end when it does, echoed as
        box.finish() would.

        Returns:
            The coroutine's result, or None when Ctrl+C (or the app
            stopping) cancelled it.

        Raises:
            Whatever the coroutine raises, after its boxes are echoed.
            TypeError: If given something other than a coroutine (call the
                function: query(respond(text))).
            RuntimeError: Outside ``async with session:``, or while another
                query runs (start a task for work beside the next input).

        Example:
            async with session:
                while True:
                    try:
                        text = await session.prompt_async()
                    except (EOFError, KeyboardInterrupt):
                        break
                    await session.query(respond(text))
        """
        if not asyncio.iscoroutine(coro):
            raise TypeError(
                f"query() takes a coroutine: call the function, as in "
                f"query(respond(text)); got {coro!r}"
            )
        if self._app_run is None:
            coro.close()
            raise RuntimeError(
                "query() runs a query of a running session: "
                "call it inside `async with session:`"
            )
        return await self._run_query(coro)

    async def _run_query(self, coro: Coroutine[Any, Any, _T]) -> _T | None:
        """The foreground-query core, shared by query() and run_async's
        handlers (it doesn't check that the app runs)."""
        foreground = self._foreground
        if foreground is not None and not foreground.done():
            coro.close()
            raise RuntimeError(
                "A query is already running: one at a time "
                "(start a task for work beside it)"
            )
        task: asyncio.Task[_T] = asyncio.ensure_future(coro)
        self._foreground = task
        try:
            try:
                # wait() rather than await: the query's cancellation (Ctrl+C,
                # the app stopping) and this task's own stay apart.
                await asyncio.wait({task})
            except asyncio.CancelledError:
                # This task is being cancelled, not the query: the query
                # goes too, and its boxes end once it has unwound.
                task.cancel()
                await asyncio.wait({task})
                self._cleanup_after_handler(task, cancelled=True)
                raise
            if task.cancelled():
                # Ctrl+C, or the app stopping: the query ends, the loop goes on.
                self._cleanup_after_handler(task, cancelled=True)
                return None
            # Its boxes are echoed before its result or its error.
            self._cleanup_after_handler(task)
            return task.result()
        finally:
            self._foreground = None
            if self._cancel_line_pending:
                # One line after all the boxes the Ctrl+C ended, those of
                # the query's sub-tasks too.
                self._cancel_line_pending = False
                self._display.system("Operation cancelled...")
                self._invalidate()
            # Always clear the cancel flag for the next query: if the query
            # catches CancelledError and returns, or the cancel races its
            # natural end, nothing else would, and the next outer
            # cancellation would look like a Ctrl+C.
            self._user_cancelled_handler = False

    async def run_async(
        self,
        handler: InputHandler | None = None,
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

        When the session ends, its last frame leaves out the thinking boxes
        and the status bar. The boxes nobody else will end (see the README's
        "When a Box Ends") are echoed below it. A box a live task is feeding
        is left to that task: it's echoed when the task finishes it, or else
        when the task ends.

        Raises:
            ValueError: If no handler is provided and none was registered.

        Example:
            # Option 1: Pass handler directly
            async def handle(text):
                async with session.thinking() as box:
                    box.append("Working...\\n")
                    await asyncio.sleep(1)

            await session.run_async(handle)

            # Option 2: Use @on_input decorator
            @session.on_input
            async def handle(text):
                ...

            await session.run_async()  # Uses registered handler
        """
        effective_handler = handler or self._input_handler
        if effective_handler is None:
            raise ValueError(
                "No handler provided. Either pass a handler to run_async() "
                "or register one with @session.on_input decorator."
            )
        async with self:
            # The input loop runs in a task of its own: boxes a sync handler
            # opens are its own, not the app's (an app's startup box is).
            loop = asyncio.ensure_future(self._input_loop(effective_handler))
            # The loop must not outlive the app: when the app stops first
            # (Ctrl+D, exit()), the loop goes too, a running handler with it.
            assert self._app_run is not None
            self._app_run.add_done_callback(lambda _run: loop.cancel())
            try:
                # wait() rather than await: the loop's cancellation ends the
                # run quietly; run_async()'s own cancellation propagates.
                await asyncio.wait({loop})
            finally:
                loop.cancel()
                with suppress(asyncio.CancelledError):
                    await loop

    async def _input_loop(self, handler: InputHandler) -> None:
        """run_async()'s loop: each input to the handler, until the app
        stops (EOFError) or Ctrl+C exits at an idle prompt."""
        while True:
            try:
                text = await self.prompt_async()
                await self._run_handler(handler, text)
            except (EOFError, KeyboardInterrupt):
                return

    async def _run_handler(
        self,
        handler: InputHandler,
        text: str,
    ) -> None:
        """Invoke the input handler with cancellation and cleanup hooks.

        A sync handler runs in this task; any boxes it left open are
        finished when it returns or raises, so the UI cannot get stuck in a
        "thinking" state. An async handler runs as the foreground query
        (_run_query): Ctrl+C cancels it, and its boxes end with it. An
        outer cancellation propagates.
        """
        # A sync handler (and the sync start of an async one) runs in this
        # task: boxes it opens are owned by it.
        caller = asyncio.current_task()
        try:
            result = handler(text)
        except Exception as e:
            self._cleanup_after_handler(caller)
            self._report_handler_error(e)
            return

        if not asyncio.iscoroutine(result):
            # Sync handler — already complete. Finish any boxes it left
            # open so the UI can't get stuck in a "thinking" state.
            self._cleanup_after_handler(caller)
            return

        try:
            await self._run_query(result)
        except Exception as e:
            # The boxes' content is echoed, then the error line.
            self._report_handler_error(e)

    def _report_handler_error(self, exc: Exception) -> None:
        """Log a handler exception with its traceback; show it on screen.

        The screen line names the exception type — str() alone renders
        KeyError('x') as just 'x'. The traceback goes to the
        ``thinking_prompt`` logger, visible once the app configures logging.
        """
        logger.error("Input handler raised", exc_info=exc)
        detail = format_exception_detail(exc)
        self.add_error(f"Handler error: {detail}")

    def _exit_app(self) -> None:
        """Exit the app unless it is not running or already exiting."""
        future = self.app.future
        if self.app.is_running and future is not None and not future.done():
            self.app.exit()

    def _cleanup_after_handler(
        self, owner: asyncio.Task[Any] | None, *, cancelled: bool = False
    ) -> None:
        """Finish the boxes the ended handler answers for.

        See ThinkingBoxManager.finish_owned_by. Their content is echoed;
        when the handler was cancelled, "Operation cancelled..." follows.
        """
        ended = self._manager.finish_owned_by(owner)
        if cancelled:
            self._announce_cancel(bool(ended))

    def run(self, handler: InputHandler | None = None) -> None:
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
        """Get the current status bar text (a hint, while one shows)."""
        return self._status_now()

    @status_text.setter
    def status_text(self, value: Any) -> None:
        """Set the status bar text: plain or formatted text (FormattedText,
        HTML, ANSI, a callable), or a Rich renderable."""
        if _is_rich_renderable(value):
            value = self._display.to_ansi(value)
        self._status_text = value
        self._invalidate()

    # =========================================================================
    # Dialog API
    # =========================================================================

    @property
    def dialog_placement(self) -> Placement:
        """How dialogs are drawn unless the dialog (or the call) says otherwise."""
        return self._dialog_placement

    def _inline_dialog_content(self) -> AnyContainer:
        """What the layout's inline-dialog slot shows: the open inline dialog,
        rows for an open box dialog to float over, or nothing.

        A box dialog floats over the layout without asking for rows: with
        the prompt at the bottom of the terminal, it was clipped to the
        prompt's few rows. Rows here put it where an inline dialog would
        be, sharing the terminal with the rest of the layout the way an
        inline dialog does.
        """
        manager = self._dialog_manager
        if manager is None:
            return self._no_inline_dialog
        if manager.inline_view is not None:
            return manager.inline_view.container
        return self._box_dialog_room

    def _box_room(self) -> tuple[Window, int] | None:
        """The window holding a box dialog's reserved rows and the rows it
        got, if it is in the layout now and was drawn in this render, else
        None. The rest of the layout (a thinking box, a longer prompt) can
        leave it fewer than it asked for."""
        room = self._box_dialog_room
        if self._inline_dialog_content() is not room:
            return None
        drawn = self._room_control.drawn
        if drawn is None or drawn[0] != self.app.render_counter:
            return None
        return room, drawn[1]

    def _box_dialog_rows(self) -> Dimension:
        """The box dialog's rows, to reserve. Flexible down to none, so a
        dialog taller than the terminal can't overflow the layout."""
        manager = self._dialog_manager
        size = self.app.output.get_size()
        rows = manager.box_rows(size.columns, size.rows) if manager is not None else 0
        return Dimension(min=0, preferred=rows, max=rows)

    @property
    def _dialogs(self) -> DialogManager:
        """Get or create the dialog manager (lazy initialization)."""
        if self._dialog_manager is None:
            from .dialog import DialogManager
            self._dialog_manager = DialogManager(self)
        return self._dialog_manager

    def _resolve_placement(self, placement: Placement | None) -> Placement:
        """``placement``, or the session's dialog_placement when None (validated)."""
        check_placement(placement, optional=True)
        return placement if placement is not None else self._dialog_placement

    async def yes_no_dialog(
        self,
        title: str,
        text: str,
        yes_text: str = "Yes",
        no_text: str = "No",
        *,
        placement: Placement | None = None,
        max_height: int | None = None,
    ) -> bool:
        """
        Show a Yes/No confirmation dialog.

        Args:
            title: Dialog title.
            text: Dialog body text.
            yes_text: Text for Yes button (default: "Yes").
            no_text: Text for No button (default: "No").
            placement: "box" or "inline"; None (default) uses the session's
                dialog_placement.
            max_height: The most rows the dialog takes; what doesn't fit
                scrolls (see Dialog.max_height). None (default): the
                terminal's rows less the prompt's.

        Returns:
            True if Yes was clicked, False if No or Escape.

        Example:
            if await session.yes_no_dialog("Confirm", "Delete this file?"):
                delete_file()
        """
        from .dialog import _yes_no_dialog
        dialog = _yes_no_dialog(title, text, yes_text, no_text, self._resolve_placement(placement), max_height)
        return cast(bool, await self._dialogs.show(dialog))

    async def message_dialog(
        self,
        title: str,
        text: str,
        ok_text: str = "OK",
        *,
        placement: Placement | None = None,
        max_height: int | None = None,
    ) -> None:
        """
        Show an informational message dialog.

        Args:
            title: Dialog title.
            text: Dialog body text.
            ok_text: Text for OK button (default: "OK").
            placement: "box" or "inline"; None (default) uses the session's
                dialog_placement.
            max_height: The most rows the dialog takes; what doesn't fit
                scrolls (see Dialog.max_height). None (default): the
                terminal's rows less the prompt's.

        Example:
            await session.message_dialog("Info", "Operation completed.")
        """
        from .dialog import _message_dialog
        dialog = _message_dialog(title, text, ok_text, self._resolve_placement(placement), max_height)
        await self._dialogs.show(dialog)

    async def choice_dialog(
        self,
        title: str,
        text: str,
        options: Sequence[str],
        *,
        placement: Placement | None = None,
        max_height: int | None = None,
    ) -> str | None:
        """
        Show a dialog with multiple choice buttons.

        Args:
            title: Dialog title.
            text: Dialog body text.
            options: The options, each a button.
            placement: "box" or "inline"; None (default) uses the session's
                dialog_placement.
            max_height: The most rows the dialog takes; what doesn't fit
                scrolls (see Dialog.max_height). None (default): the
                terminal's rows less the prompt's.

        Returns:
            The option picked, or None if Escape was pressed.

        Example:
            action = await session.choice_dialog(
                "Select Action",
                "What would you like to do?",
                ["Save", "Discard", "Cancel"],
            )
            if action == "Save":
                save_file()
        """
        from .dialog import _choice_dialog
        dialog = _choice_dialog(title, text, options, self._resolve_placement(placement), max_height)
        return cast(Optional[str], await self._dialogs.show(dialog))

    async def dropdown_dialog(
        self,
        title: str,
        text: str,
        options: Sequence[str],
        default: str | None = None,
        *,
        placement: Placement | None = None,
        max_height: int | None = None,
    ) -> str | None:
        """
        Show a dialog to pick one of ``options``: a choice list in a box,
        numbered rows inline.

        Args:
            title: Dialog title.
            text: Dialog body text.
            options: List of options to choose from.
            default: The option selected, with the cursor on it, when the
                dialog opens (optional; the first option otherwise).
            placement: "box" or "inline"; None (default) uses the session's
                dialog_placement.
            max_height: The most rows the dialog takes; what doesn't fit
                scrolls (see Dialog.max_height). None (default): the
                terminal's rows less the prompt's.

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
        from .dialog import _dropdown_dialog
        dialog = _dropdown_dialog(title, text, options, default, self._resolve_placement(placement), max_height)
        return cast(Optional[str], await self._dialogs.show(dialog))

    async def checklist_dialog(
        self,
        title: str,
        text: str,
        options: Sequence[str],
        defaults: Sequence[str] = (),
        *,
        placement: Placement | None = None,
        max_height: int | None = None,
    ) -> list[str] | None:
        """
        Show a check list: any number of options, one per line.

        Args:
            title: Dialog title.
            text: Text above the options ("" for none).
            options: The options to check.
            defaults: Options checked at first (others are ignored).
            placement: "box" or "inline"; None (default) uses the session's
                dialog_placement.
            max_height: The most rows the dialog takes; what doesn't fit
                scrolls (see Dialog.max_height). None (default): the
                terminal's rows less the prompt's.

        Returns:
            The checked options in option order, or None if cancelled.

        Raises:
            ValueError: If ``options`` is empty.

        Example:
            tools = await session.checklist_dialog(
                "Tools", "Enable any:", ["search", "code", "files"], defaults=["search"]
            )
        """
        from .dialog import _checklist_dialog
        dialog = _checklist_dialog(title, text, options, defaults, self._resolve_placement(placement), max_height)
        return cast("list[str] | None", await self._dialogs.show(dialog))

    async def show_dialog(self, dialog: Dialog) -> Any:
        """
        Show a dialog and wait for its result.

        Args:
            dialog: A Dialog, built with arguments or a subclass instance.

        Returns:
            The result value set by the dialog (a button or Escape).

        Example (built with arguments):
            from thinking_prompt import ButtonConfig, Dialog

            result = await session.show_dialog(Dialog(
                title="Custom",
                body="Choose an option:",
                buttons=[
                    ButtonConfig("Option A", result="a"),
                    ButtonConfig("Option B", result="b"),
                ],
            ))

        Example (subclass):
            from thinking_prompt import ButtonConfig, Dialog

            class MyDialog(Dialog):
                title = "My Dialog"

                def build_body(self):
                    return Label("Custom content")

                def get_buttons(self):
                    return [ButtonConfig("OK", result=True)]

            result = await session.show_dialog(MyDialog())
        """
        return await self._dialogs.show(dialog)
