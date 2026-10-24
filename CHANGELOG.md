# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.1] - 2026-10-24

### Added

- `examples/claude_chat.py`: a chat with Claude whose thinking streams into a thinking box and whose answer prints as markdown (needs `anthropic` and an API key). The README's new "Use with a model" section shows its handler.
- `examples/shell_jobs.py`: shell commands run as background jobs, each streaming into its own numbered thinking box while the prompt takes the next; `/stop N` stops one, `rm` asks first, and Ctrl+C at the prompt leaves the jobs running. No API key needed.

### Changed

- Rich output is laid out at the width of the session's terminal: `add_rich()`, markdown responses, the welcome banner, and a `Panel` or `Table` in a thinking box. Rich used to find a width on its own, from the process's terminal (80 columns without one), which needn't be the one the session prints to. After the terminal shrinks, its repaint lays markdown out again at the new width; Rich output keeps the width it was printed at. `StreamingContent.append_rich()` and `set_line_rich()` take `width=`.
- The README opens with what the library is for, badges, and a Features list that covers 0.4: dialogs, form fields and themes.
- CI runs the tests on macOS and Windows as well as Linux, and on Python 3.14; the package lists 3.14 among its supported versions. The tests run on Windows CI, which gives them no console.
- **Ctrl+C at an idle prompt leaves a live task's box to that task.** It used to end every box, so a background job's box vanished while the job ran on and its writes were dropped. It now ends only the boxes nobody else will end: those whose task ended, those opened outside asyncio, and those the app's own task opened (the task running `run_async()`, e.g. a startup status box). With only live tasks' boxes open it doesn't exit, and the status bar says `Background work is running — Ctrl+D exits` until no box is open or the next input is accepted.
- The app's last frame, drawn as it exits, leaves out the thinking boxes and the status bar, as prompt_toolkit's `PromptSession` leaves out its toolbar. A background job's box no longer stays in the scrollback above its own echo: it's echoed once, when its task ends it, or else when the task ends.

### Fixed

- Boxes nobody else will end (opened by the app's own task, or outside asyncio) that are still open when the session ends are echoed below its last frame. They were never ended, so their content was lost.
- Exiting (Ctrl+D) while a handler that Ctrl+C cancelled was still cleaning up left `run_async()` blocked for good: the app stopped, but the input loop went back to wait for input.
- `append_rich()` dropped the text's trailing whitespace, the newline that ends a line included: three `append_rich("…\n")` calls made one line, so the README's task list, `demo_multi_box.py` and `demo_task_progress.py` showed one line, and updating line 0 replaced it all. Streamed words lost the space between them. `rich_to_ansi()` keeps the text's whitespace too; `set_line_rich()` still takes markup that ends with a newline.
- A `Panel` in a thinking box (`append_rich()`) was laid out 9999 columns wide, so each of its lines wrapped into over a hundred rows, and a `Table` didn't wrap its cells to the terminal.
- A thinking box whose last line was longer than the box (a streamed paragraph) showed that line's start under `+0 earlier lines`, so new words never appeared; in head mode the hint was cut off. The box now fits by screen rows: the newest rows show (the first, in head mode), and the hint counts a line shown in part. Rows are counted as the window draws them: a wide character that doesn't fit at a row's end starts the next row, and a tab, drawn as `^I`, takes two columns.
- In a terminal too narrow for the overflow hint (under about 37 columns), the hint wrapped onto a second row the box hadn't reserved, pushing the newest row out of view. The hint now gets the rows it wraps to; a box left with no row for content beside it shows content only, as a one-row box does.
- A thinking box parsed its whole text six times a frame (five height checks and the draw), so streaming slowed as the box grew: a frame of a 10,000-line ANSI box took about 730 ms. The text is now parsed once, and text streamed in only from its last line on, after one color code that sets the style in force there; each line's rows are counted once per width. That frame now takes under a millisecond, and the first draw about 120 ms. Lines are kept as style runs, not a fragment a character. Text changed before its last line (`set_line()` on an earlier line, `clear()`), or ANSI text after an escape other than a color code, is parsed whole again.

### Removed

- `ThinkingBoxManager.finish_all()` (the manager isn't exported): idle Ctrl+C ends only the boxes nobody else will end (`finish_owned_by()`).

## [0.4.0] - 2026-10-17

Many changes here are breaking: entries marked **Breaking** need code changes, and the README's "Upgrading from 0.3" notes show the replacements.

### Added

- Built-in themes: `theme=` constructor parameter accepting `"dark"` (default), `"light"`, `"mono"`, `"terminal"` (inherits the terminal palette), `"auto"`, or a `ThinkingPromptStyles` instance. `ThinkingPromptStyles` factories: `.dark()/.light()/.mono()/.terminal()`.
- `NO_COLOR` support (non-empty env var, read at startup) and mono rendering enforced at the render layer via prompt_toolkit color depth — strips color from rich/pygments output too, keeps bold/italic.
- Runtime theme switching: `session.set_theme(name_or_styles, repaint=False)`; with `repaint=True` clears screen+scrollback and re-prints the transcript (markdown/code re-render from source; `add_rich`/raw ANSI stays as originally rendered).
- `history_limit=` session parameter bounding transcript entries.
- All `ThinkingPromptStyles` element styles now derive from `color_*` tokens (9 new tokens; dark defaults byte-identical), resolved at render time so `dataclasses.replace()` or assigning a token restyles everything not explicitly overridden. New fields: `color_depth`, `code_theme` (a Pygments style name, or `"ansi_dark"`/`"ansi_light"` for the terminal's own colors; drives both markdown code fences and `add_code()`).
- `ThinkingPromptStyles.to_style_dict()`: the resolved style rules by class name, for inspecting what a theme renders.
- `Dialog`: one concrete dialog class. Build it with arguments (`Dialog(title, body, buttons, escapable=..., width=..., max_height=...)`) or subclass it and override `build_body()` / `get_buttons()`. Its class attributes are the only defaults. `body` may be text (str, HTML, ANSI) or any prompt_toolkit container.
- `escapable: bool` on `Dialog` (default `True`): the public way to make Escape do nothing, so only a button closes the dialog. `escape_result` only says what Escape returns.
- `ButtonConfig(handler=...)`: a button that runs logic on click (validate, read fields) and decides whether to close via `set_result()` / `cancel()`. A handler that raises is logged and reported; the dialog stays open.
- `overflow="tail" | "head"` on `start_thinking()` and `thinking()` (and the exported `Overflow` type): which end of overflowing thinking content stays visible, in the box and in the echo when it finishes.
- Typed transcript history: markdown/code stored by source with per-theme render caches; ANSI fragments coalesced (fixes per-character fragment memory amplification).
- **Inline dialogs**: `placement="box" | "inline"` on `Dialog`, `dialog_placement=` on the session (default `"box"`) and `placement=` on every dialog helper. Inline dialogs are drawn as rows between the prompt and the status bar: a numbered action per button, one cursor (↑↓ / Tab, Enter, 1–9, Esc) and a key hint; form fields are edited in place, and a dropdown opens its menu under its row, as in a box. The `Placement` type is exported.
- **Form fields on any `Dialog`:** `fields=[...]` (or a subclass's `fields` class attribute) shows `TextField`, `CheckboxField`, `SelectField`, `DropdownField`, `ChecklistField` and `RadioField` under the body, in box and inline dialogs, and `dialog.values` holds what they're set to, by key. `align_values=` sets where their values start. A settings dialog is now client code: a `Dialog` with fields and Save/Cancel buttons (see the README's Form fields).
- `Dialog(values=...)`: the fields' starting values by key, over their defaults; keys that aren't fields are ignored, so `values=config` works. Each show starts afresh from them (read again at each show) or from the defaults, so a dialog shown again doesn't keep what the last show left, cancelled edits included.
- `checklist_dialog()`: check any number of options; returns the checked ones in option order, or `None`.
- `ChecklistField` and `RadioField`: one option per line, in box and inline dialogs.
- `ChoiceField`: a radio list drawn like prompt_toolkit's `choice()`: no `(•)` marks, the pick in bold. ↑↓ walk the options and Space or Enter picks one, as in a `RadioField`. As a dialog's only field (with nothing in the body taking focus), Enter also presses the dialog's first button, or with no buttons closes the dialog with the pick.
- `ThinkingPromptStyles` fields `dialog_choice`, `dialog_choice_selected` and `dialog_hint` for inline dialogs; `dialog_title` also styles the inline title.
- `ThinkingBox.is_finished`: True once the box is finished, by `finish()` or by the session.
- `Spinner(frames, interval=0.1)`: a thinking header's animation, its frames with the seconds each is shown. Presets: `Spinner.DOTS` (the braille default), `Spinner.LINE` (ASCII only) and `Spinner.ELLIPSIS`. A one-frame spinner is a static mark and asks for no redraws. Set it with `ThinkingPromptSession(spinner=...)`; the frame speed couldn't be set from the session or `AppInfo` before.
- `max_height=` on `Dialog` and every dialog helper: the most rows a dialog takes, all of it counted. Content beyond it scrolls: rows with a cursor follow it, and a text body scrolls with PgUp/PgDn (and ↑↓ in a box); an inline dialog's hint line says so while the text overflows.
- `align_values=` on `Dialog`, for its fields: `"labels"` (the default: values two columns after the longest label or description, so descriptions don't run under them, as far right as the widest value still fits), `"right"` (the row's right edge, the old look) or a column number (longer labels cut with `…`).
- A box dialog too big for the terminal (narrower than its buttons, or shorter than its frame, buttons and one body row) shows a notice with the size it needs instead of collapsing to an empty frame. Keys still reach the hidden dialog: Esc cancels it and Enter presses its focused button, and the dialog comes back when the terminal grows.
- `examples/demo.tape`: a VHS script that records the README's demo GIF from `demo_showcase.py` (`vhs examples/demo.tape`). The GIF is re-recorded with it, in a 100×38 terminal so its text shows bigger in the README.

### Changed

- A box dialog sits where an inline dialog would, under the prompt above the status bar. It shares the rows with the rest of the screen as an inline dialog does: when a thinking box or a longer prompt takes some, the box takes the rows it gets and scrolls the rest, instead of being centered over them. Only rows fewer than its title, one row and its buttons need still center it.
- **Breaking:** `ThinkingPromptStyles` element fields hold only explicit overrides; derived styles are no longer written into them at construction. Reading a derived field (e.g. `styles.error_message`) now returns `""` unless it was set explicitly — use `to_style_dict()` to inspect resolved styles.
- `add_code()` highlights in the theme's `code_theme` (monokai in the default dark theme, matching markdown code fences) instead of Pygments' light-background terminal palette, and re-renders in the new theme on `set_theme()`.
- A text field shows the theme's input background (`text_area`) while editing.
- **Thinking boxes keep their newest lines when content overflows** (under `+N earlier lines... ctrl-t to expand`), instead of freezing on the first lines while a stream arrives out of sight; the finish echo keeps the last lines too. Pass `overflow="head"` for the previous behavior, e.g. for task lists.
- Thinking boxes fit content to the rows they get, counting wrapped lines: content of exactly `max_lines` lines now fits without a hint, and "1 line" is singular.
- Expanded thinking boxes (Ctrl+T) size to their content instead of a fixed 20 rows; on a short screen they are squeezed and follow the newest lines (the unusable scrollbar is gone).
- Form fields mark the highlighted row with `❯` (was `>`).
- `ThinkingPromptStyles.checkbox_mark` now styles the `[x]` / `(•)` marks of check and radio lists (it styled nothing before).
- **Thinking content is kept however a box ends** (it was discarded on cancel and error). On Ctrl+C each cancelled box's content is echoed, then one `Operation cancelled...` line, also after an empty box. The same happens when the task running a `thinking()` block is cancelled. When a handler raises, its boxes' content is echoed before the `Handler error` line. A box the handler leaves open, or a `thinking()` block that raises, is finished like `box.finish()`.
- Thinking boxes belong to the task that opened them. When a handler ends or is cancelled, the session finishes only the boxes that handler answers for: its own, those whose task already ended, and those opened outside asyncio. Ctrl+C at an idle prompt still clears every box.
- `box.finish()` can be called again, including after the session finished the box. It returns the same text without echoing it twice. Writes to a finished box are dropped, so `box.text` stays what `finish()` returned; the first one logs a warning (they used to be dropped silently, then shown nowhere while still changing `get_content()`).
- **The screen is redrawn only when something changes**, instead of 10 times a second for the whole session, idle prompt included. At an idle prompt, redraws went from 10 a second to none, and CPU from about 37 ms a second to under 1 ms. Writes to a box redraw right away, from any thread, capped at 30 redraws a second for fast streams. A spinner asks for its next frame while its box is drawn: spinners share one redraw per frame and stop when their boxes close. A content callback passed to `start_thinking()`, and a `message` or `status_text` given as a callable, are re-read every 0.1 s while they're drawn. `ThinkingBoxManager(frames=)`, `ThinkingHeader(request_frame=)`, `ThinkingBoxControl(on_draw=)` and `StreamingContent(on_change=)` wire this up.
- Expansion is one mode shared by all thinking boxes, and it resets to collapsed when the last box finishes.
- **Breaking:** `set_line()` and `set_line_rich()` take one line. Text with a newline, or markup that renders to several lines (a `Panel`, a `Table`), raises `ValueError`. `set_line()` used to insert the extra lines, shifting every line after them, and `set_line_rich()` silently dropped all but the first.
- The exported `InputHandler` and `ContentCallback` types now type the session's parameters: `on_input()`, `run()` and `run_async()` take an `InputHandler`, `start_thinking()` a `ContentCallback`. `on_input()` returns the handler with its own type. `InputHandler`'s async form is a coroutine function (`Callable[[str], Coroutine[Any, Any, None]]`, was `Awaitable`), which is what the session runs as a task.
- **Breaking:** `ThinkingContext` is now `ThinkingBox`: `start_thinking()` returns one and `thinking()` yields one, with the same methods. It is the box itself rather than a wrapper around callbacks, and it isn't constructed directly.
- A box started with a content callback can be read: `box.text` and `get_content()` return what it shows, and once it's finished, the text it had then. Writing to it (`append()`, `set_line()`, `clear()`, the `_rich` variants, `len()`) raises `TypeError` saying the box shows a content callback's text; it used to raise `AttributeError` with a hint to use `thinking()`.
- `append_rich()` and `set_line_rich()` use the session's current Rich theme, read at each write; a box used to keep the theme it started with.
- **Breaking:** `len()` of a thinking box and of `StreamingContent` counts lines, not the chunks written. A trailing newline ends a line rather than starting one: `"a"` and `"a\n"` are one line, `""` is none. `set_line()` numbers lines the same way, so `-1` is the last line, and `set_line(-1, ...)` on an empty box raises `IndexError` (it used to write line 0). `StreamingContent` keeps its text as lines, so `set_line()` replaces one line instead of rebuilding the whole text.
- **Breaking:** `ThinkingPromptSession(spinner=...)` replaces `AppInfo(thinking_animation=...)`, and `spinner_position=` replaces `thinking_animation_position`. `spinner=None` turns the spinner off (was `thinking_animation=()`). `ThinkingHeader(spinner=...)` replaces its `frames=` and `animation_interval=`, and `ThinkingBoxManager(spinner=...)` replaces `spinner_frames=`. `DEFAULT_SPINNER_FRAMES` is gone (`Spinner.DOTS.frames`), and so is the `ThinkingSeparator` alias for `ThinkingHeader`.
- **Breaking:** `AppInfo` is only the startup banner: `name`, `version` and `welcome_message`. Its behavior settings are now `ThinkingPromptSession` arguments with the same defaults: `expand_key`, `thinking_title` (was `thinking_text`), `spinner`, `spinner_position` and `echo_thinking` (`fullscreen_enabled` and `fullscreen_key` went with full screen; see Removed). Key bindings and the thinking header no longer need an `AppInfo`, which always printed a banner. Every `ThinkingPromptSession` argument after `message` is keyword-only. Migration:

  ```python
  # 0.3
  ThinkingPromptSession(app_info=AppInfo(name="App", expand_key="c-x", thinking_text="Working"))
  # 0.4
  ThinkingPromptSession(app_info=AppInfo(name="App"), expand_key="c-x", thinking_title="Working")
  ```
- `StreamingContent` moved to `thinking_prompt.streaming`, and the box control module `thinking_prompt.thinking` is now `thinking_prompt.thinking_control`. `from thinking_prompt import StreamingContent` is unchanged.
- A box dialog fits the terminal: content taller than the terminal (less the prompt's rows) scrolls instead of being cut off, and so does an inline dialog's text body.
- Field values start right after their labels instead of at the row's right edge, where an inline dialog in a wide terminal put them far from their labels. `align_values="right"` keeps the old look.
- Field rows short of width give way in order: the label is cut first (down to 3 columns), then a dropdown or text field gives up its padding, then the value is cut with `…`. `align_values="right"` now cuts long labels too, where it used to push the value off the row, and a text field being edited keeps at least 8 columns (or its `edit_width`, if smaller), scrolling sideways.
- In a box, Tab and Shift+Tab move a field at a time: from anywhere in a check or radio list, Tab goes on to the next field (or the buttons), Shift+Tab from the buttons comes back to the last field, and a radio or choice list is always entered at its picked option (also when Tab wraps round from the last button). ↑↓ still move a row at a time.
- `dropdown_dialog()` in a box is a `ChoiceField`: options drawn like prompt_toolkit's `choice()` (`❯ option`, the pick in bold, no `(•)` marks); ↑↓ move the cursor and Enter returns the option under it (OK still returns the pick; Tab reaches the buttons). A long list's question scrolls with the options (it shows at the top), as a check list's text does.

### Removed

- **Breaking:** full screen is removed: `AppInfo(fullscreen_enabled=, fullscreen_key=)` (Ctrl+E), `session.is_fullscreen`, `switch_to_fullscreen()` and `switch_to_prompt()`. It showed the transcript in a window above the prompt, which always scrolled back to its oldest lines, and expanded every thinking box, which Ctrl+T does. The terminal's own scrollback holds the transcript, with its search and selection; mouse support, which only served that window, is gone with it. Internals that served it are gone too: `Display(is_fullscreen=)`, `flush_pending()`, `drop_pending()` and `set_on_change()`, `FormattedTextHistory.set_on_change()` and `revision`, `ThinkingBoxManager.force_expanded()`, and `create_layout(history=, is_fullscreen=)` with `create_history_window()`. `history_limit` still caps the transcript a repaint prints.
- **Breaking:** the dialogs' `top` attribute (no alias; a subclass's `top` is now ignored). A box sits under the prompt, where an inline dialog would; `top` counted from the app's first row, which moves as output is printed.
- **Breaking:** `DialogConfig` and `BaseDialog` are removed (no deprecation period). `Dialog` replaces both. `get_buttons()` must return `ButtonConfig` items (tuples raise `TypeError` with a hint), `escape_result=_UNSET` is gone (use `escapable=False`), and `show_dialog()` raises `TypeError` for anything but a `Dialog`. The default dialog title is now empty instead of `"Dialog"`. Migration:

  ```python
  # 0.3                                        # 0.4
  DialogConfig(title, body, buttons, ...)   →  Dialog(title, body, buttons, ...)
  class MyDialog(BaseDialog): ...           →  class MyDialog(Dialog): ...
  return [("OK", self.on_ok)]               →  return [ButtonConfig("OK", handler=self.on_ok)]
  escape_result = _UNSET                    →  escapable = False
  ```

  `Dialog` has no default buttons, so `BaseDialog` subclasses that relied on the inherited OK button must add it (`buttons = (ButtonConfig("OK"),)`); a dialog with nothing to focus (no buttons and a text body) raises `ValueError` at `show_dialog()`. `ButtonConfig` is now immutable (frozen) and rejects async handlers and `result=` together with `handler=`.
- **Breaking:** `ThinkingBoxControl.expand()`, `collapse()` and `toggle_expanded()` are removed. A box reads the `expanded=` predicate it is given; `ThinkingBoxManager` passes its shared mode, which `toggle_all()` / `expand_all()` / `collapse_all()` set.
- **Breaking:** the session's `styles=` parameter is removed; `theme=` accepts a `ThinkingPromptStyles` instance (`ThinkingPromptSession(styles=s)` → `ThinkingPromptSession(theme=s)`).
- **Breaking:** the `ThinkingPromptStyles` fields `assistant_prefix`, `select_value` and `user_separator` are removed, with their style classes. No component drew with them, so setting them did nothing. The dead `completion-menu.meta.current` rule is gone too (`menu_meta_selected` still styles the selected completion's meta via `completion-menu.meta.completion.current`).
- **Breaking:** `finish_thinking()`, deprecated since 0.3.0. Finish each box through its handle (`box.finish()`) or use the `thinking()` context manager.
- **Breaking:** the `MessageRole` type. Nothing used it. The unexported `SyncInputHandler` / `AsyncInputHandler` aliases are gone too, and the text helpers `split_content_lines`, `truncate_to_lines`, `truncate_ansi_to_lines` and `format_exception_detail` moved from `thinking_prompt.types` to a private module.
- **Breaking:** `ThinkingBoxControl.start()`, `finish()`, `final_content` and `is_active` are removed: the control only draws, and takes the text to draw as its first argument, `ThinkingBoxControl(get_text, ...)`. `ThinkingBoxManager` takes the session's `Display` as its first argument and ends boxes with `finish(box)`, `finish_all()` and `finish_owned_by(task)`, which return the boxes they ended; `remove_box()`, `has_box()`, box ids and `ManagedBox` are removed.
- **Breaking:** the dialogs' `height` (`BaseDialog.height`, and `height=` on the settings dialog): use `max_height=`, which sizes the dialog to its content up to that many rows. A dialog is no longer refused in a terminal under 12 rows ("Not enough room to show dialog"): it opens smaller and scrolls.
- **Breaking:** the settings dialog: `SettingsDialog`, `session.show_settings_dialog()`, `can_cancel`, its changed-values result and its Ctrl+S. Build one from `Dialog(fields=...)` (README: Form fields).
- **Breaking:** `SettingsItem`, `InlineSelectItem`, `DropdownItem`, `CheckboxItem`, `TextItem`, `ChecklistItem` and `RadioItem` are `Field`, `SelectField`, `DropdownField`, `CheckboxField`, `TextField`, `ChecklistField` and `RadioField` (frozen dataclasses with the same attributes), in `thinking_prompt.fields`.
- **Breaking:** the `setting_*` style fields are `field_*` (`setting_label` → `field_label`, and so on), and the `setting-*` style classes are `field-*`.
- **Breaking:** `ThinkingHeader.reset()`, which nothing called; a box's spinner starts at its first frame anyway.

### Fixed

- A `DropdownField` with a `width` or `max_width` below 0 failed inside prompt_toolkit when its menu opened. `DropdownField` (`height`, `width`, `max_width`) and `TextField` (`edit_width`) now refuse sizes below 1 with a `ValueError` when they're made; `width` and `max_width` may still be None.
- Shrinking the terminal no longer leaves copies of the prompt, separators and dialogs behind. A narrower window re-wraps the UI's full-width rows and a shorter one pushes its top into scrollback, so prompt_toolkit's row-by-row erase missed part of each frame, and it came back when the window grew. Once the size holds for 0.25 s after getting narrower or shorter, the session clears the screen and scrollback and prints the transcript again, as `set_theme(repaint=True)` does. Shell output from before the session and plain `print()` output are not kept.
- A dropdown's menu opens under its own row instead of at the form's second row, covering its own; it's sized to the terminal (opening above the row when there's more room there) with a scrollbar when not every option fits.
- A box dialog's `width=` narrower than its buttons no longer collapses it to an empty frame: the box is at least as wide as its buttons.
- Ctrl+C with a thinking box open at an idle prompt (e.g. a startup status box) no longer leaves a zombie session. The binding cancelled the live pending-input future even when it wasn't exiting, ending the input loop while the app kept running; typed input was echoed and silently dropped. As a root-cause guard, `run_async()` now exits the app whenever its input loop ends, however it ends (e.g. `KeyboardInterrupt` escaping a sync handler).
- Submitted input is never silently dropped. A second line arriving in the same read as the first (typed ahead during a blocking handler) was echoed into the transcript and discarded. And the 0.3.2 busy guard returned the wrong value from `accept_handler` (it means *keep_text*), so pressing Enter while a handler ran cleared the draft instead of keeping it. Enter is now refused whenever nobody is waiting for input; the draft stays in the buffer, unechoed and out of input history, until submitted again.
- Ctrl+D while editing a dialog text field now deletes a character instead of exiting the whole session. The EOF binding now also requires the main prompt to have focus.
- A dialog that fails to open (an exception in a custom `build_body()`, or nothing focusable) no longer leaves the dialog manager stuck, which made every later dialog raise "A dialog is already being shown". A dialog with nothing focusable — e.g. `Dialog(title, body, buttons=[])` — now raises a `ValueError` that says so.
- A trailing newline no longer counts as a hidden thinking line. With the documented `append("...\n")` pattern, a box whose content fit showed `+1 lines... ctrl-t to expand` with nothing hidden, the hidden count was one too high when truncating, and the console echo appended a spurious `...` that the repaint didn't reproduce. The box, the echo and the repaint now share one line-splitting helper.
- HTML and ANSI prompt messages are echoed as their visible text instead of their repr (`HTML('<ansigreen>&gt;...')hello`).
- `SelectField` (was `InlineSelectItem`) without a default (or with a default that isn't an option) no longer skips the first option: the first press in either direction now selects `options[0]`. An untouched one keeps `None`.
- A thinking box handle is always truthy. Truthiness fell back to `__len__`, so `if box:` was False for a freshly started box and raised `AttributeError` for a box started with a content callback. `len(box)` still works and counts lines.
- `ThinkingPromptStyles.prompt` is now applied (the prompt window carried no class), and the text field no longer uses the undefined `class:setting-input`, which made it ignore the theme.
- The `ThinkingPromptStyles` docstring example used a nonexistent `menu_selected` field.
- Handler exceptions are logged with their traceback to the `thinking_prompt` logger, and the on-screen line names the exception type (`Handler error: KeyError: 'x'` instead of `Handler error: 'x'`). The package logger has a `NullHandler`, so nothing is printed over the UI unless the app configures logging.
- The "Busy — press Ctrl+C to cancel" status hint no longer replaces the status bar permanently: the previous status returns once input is accepted again, unless something set a new status meanwhile.
- `dropdown_dialog()` with no options raises a clear `ValueError` instead of a bare `AssertionError` from prompt_toolkit.
- Dialogs no longer wait forever when no app can answer them. `show_dialog()` and the dialog helpers raise `RuntimeError` on a session that isn't running (before `run_async()` or after it ended). A dialog still open when the app exits — e.g. one opened from a background task — is cancelled, so awaiting it raises `CancelledError`, as a dialog awaited by the input handler already did. Previously it waited forever, and the manager kept it, so every later dialog raised "A dialog is already being shown".
- Ctrl+T at an idle prompt is transpose-chars again after thinking boxes were expanded. The expand mode outlived the last box, so the key stayed bound to an empty toggle.
- A background task's thinking box is no longer finished when an unrelated handler ends or is cancelled. Its content used to be lost.
- A thinking content callback that raises is logged once per box instead of on every redraw.
- `ThinkingPromptStyles.select_arrow` now styles the ◀ ▶ and ▼ arrows of select and dropdown fields (layered over the row's value style). The arrows were drawn as part of the value text, so the field styled nothing.
- A box dialog opens whole when the prompt is near the bottom of the terminal. The app only gets the rows its layout asks for, and a box dialog floats over the layout without asking for any: it was clipped to the prompt's few rows and grew a row at each redraw, and a dialog with `height=` lost its title and top rows. The layout now reserves an open box dialog's rows.
- `dropdown_dialog(default=...)` in a box opens with the cursor on the default. The default was marked `(•)` but the cursor sat on the first option, so pressing Enter or Space in the list picked the first option instead.
- An empty welcome message prints nothing. `AppInfo(welcome_message="")` printed a blank line, and a `welcome_message` callable returning `None` printed `None`.
- Sessions created without `theme=` no longer share the module-level `DEFAULT_STYLES` instance. Setting a field through one session's `.styles` changed `DEFAULT_STYLES` and the theme of every later session.
- A long text body in a box dialog with a fixed height couldn't be scrolled: only its first rows ever showed.
- A box dialog with no `width` is as wide as its field rows and check-list options; it was as wide as its title and buttons, cutting long labels and options.
- A dropdown's menu measures options in terminal columns: a wide-character option no longer overflows the menu and cuts off its scrollbar, and a cut option ends in `…`.
- The PyPI page shows the README's demo GIF: the package description links `img/` files on GitHub's `main` (rewritten at build time by `hatch-fancy-pypi-readme`); `README.md` keeps its relative links.
- `start_thinking(max_lines=)` / `thinking(max_lines=)` below 1 raises `ValueError` when the box is made; before, the next redraw failed inside prompt_toolkit.
- The source distribution holds only the package, its tests and examples, the README, the changelog and the demo image. It took every file git doesn't ignore, so the 0.3.3 and 0.3.4 sdists also carried untracked local files (`AGENTS.md`, and in 0.3.4 an agent workspace under `.superpowers/`).

## [0.3.4] - 2026-07-04

### Fixed

- Input handlers that return without finishing their thinking boxes no longer leave the UI stuck with a permanently animating orphan box. `_run_handler` now finishes leftover boxes on normal completion — both async and sync handlers — matching the cleanup already performed on the cancellation and error paths. Leftover content is discarded, as on the Ctrl+C path. Behavior change for the edge case of a box deliberately left open across handler returns: it is now finished (content discarded) when the handler completes — keep the handler running (async) for the lifetime of such a box instead.
- Ctrl+D now resolves a pending `prompt_async()` with the documented `EOFError` instead of leaving direct callers hanging forever, and only exits on an empty input line (readline semantics). With text in the buffer, prompt_toolkit's default emacs binding deletes the character under the cursor instead of discarding the draft and killing the session.
- Collapsed thinking-box height is computed against the real terminal width instead of a hardcoded 80 columns, so wrapped lines no longer clip content on narrow terminals or reserve excess height on wide ones.
- `examples/completer_demo.py` `/quit` now exits via `session.exit()`. The previous `raise KeyboardInterrupt` escaped the handler wrapper (`except Exception`), killed the input loop without exiting the app, and left a zombie UI.
- Docstrings no longer teach broken or deprecated code: the `ThinkingPromptSession` class, `on_input`, and `run_async` examples use the `thinking()` context manager instead of the deprecated `finish_thinking()`, and the `on_input` example no longer passes a nonexistent `header=` kwarg. README no longer claims `set_status()` parses Rich markup strings — pass `Text.from_markup(...)` instead. The package docstring's key-binding list notes the empty-line qualifier as well. README's key-bindings table carries the same qualifier, and its examples list now includes `chat_demo.py` and `clear_demo.py`.

### Changed

- Dependency floors corrected: `prompt_toolkit>=3.0.36` (the old `>=3.0.0` floor resolved but crashed at import — `ScrollablePane`, used by the dialog system, was added in 3.0.15), `pygments>=2.15.0` (ReDoS hardening), and `rich` capped `<16` (the markdown renderer subclasses `rich.markdown.Heading` internals; 13–15 are the tested majors). New standalone `pygments` extra for code highlighting without rich.
- CI: Python 3.13 added to the test matrix, plus a minimal job that runs the suite without optional extras so the rich fallback paths are actually exercised. Rich-dependent tests now skip cleanly when rich is absent.

## [0.3.3] - 2026-06-13

### Fixed

- First Ctrl+C at an idle prompt now exits the session. Previously the live pending-input future was treated as in-flight work: the binding cancelled it (killing the input loop) but never exited the app, leaving a zombie session that echoed typed input without delivering it; only a second Ctrl+C exited. Behavior change for apps driving `prompt_async()` directly with their own loop: Ctrl+C at an idle prompt now also calls `app.exit()` in addition to raising `KeyboardInterrupt`, so a caller that swallowed the exception to keep the session alive will now observe the application exiting.
- `DialogManager.show()` now raises `RuntimeError` when a dialog is already open instead of overwriting it — a second concurrent dialog used to orphan the first dialog's result future, hanging its awaiter forever.
- `show_settings_dialog(can_cancel=False)` no longer returns the string `"close"` when Escape is pressed (violating the documented `dict | None` contract). Escape is now disabled in that mode; the Done button is the only way out.
- Custom `AppInfo.expand_key` is now reflected in the thinking-box truncation hint. The hint previously always read `ctrl-t to expand` even when the actual binding was different.
- `StreamingContent.set_line()` with an out-of-range negative index now raises a clear `IndexError` naming the index the caller passed, and leaves content untouched.
- The deprecated `finish_thinking()` now truncates each box to its own `max_lines` instead of the session-wide `max_thinking_height`, matching `ThinkingContext.finish()`. (`ThinkingBoxManager.finish_all()` result tuples gained a fifth element, `max_collapsed_lines`.)
- `clear()` now clears the screen through `app.renderer.clear()` while the app is running. The previous raw `\033[2J\033[H` write bypassed the renderer and left its screen state stale, corrupting the next repaint.
- Thinking-box height estimation strips ANSI styling escapes before measuring line wrap, so heavily styled `content_format="ansi"` content no longer renders an oversized box.
- The thinking header separator is sized to the terminal width instead of a hardcoded 80 columns.

### Changed

- Importing `thinking_prompt` no longer monkey-patches `rich.markdown.Markdown` globally. The left-aligned heading style is applied through an internal `Markdown` subclass used only by this library's own markdown rendering; host applications' Rich output is unaffected.
- Rich/Pygments helpers moved from `display` to a new `rich_utils` module (`display` re-exports the old names for backward compatibility). The public `rich_to_ansi` export is unchanged.
- Removed dead `ThinkingBoxControl.get_key_bindings()` and `get_console_output()` — neither had a production caller; expand/collapse is owned by the session-level binding and console truncation by `Display.thinking()`.
- `DEFAULT_SPINNER_FRAMES` now lives in `types` as the single source of truth (still importable from `layout`); `AppInfo.thinking_animation` defaults to it.
- README and docstrings now state explicitly that sync input handlers block the event loop (frozen UI, no Ctrl+C) and recommend async handlers with `asyncio.to_thread` for blocking work.
- `examples/demo_showcase.py` now sources its displayed version from `thinking_prompt.__version__` instead of a hardcoded string, so the welcome banner can't drift from the package version.

## [0.3.2] - 2026-05-01

### Fixed

- Ctrl+C now cancels a running input handler instead of letting it run to completion. The handler is tracked as an `asyncio.Task` and cancelled on Ctrl+C, with active thinking boxes finished and pending input cancelled.
- Input submitted while a handler is running is no longer silently dropped. `accept_handler` now refuses to deliver input while busy, leaves the buffer intact, and surfaces a `Busy — press Ctrl+C to cancel` status hint.
- Handler exceptions no longer leave thinking boxes stuck in the active state — cleanup runs in the exception path so callers using `start_thinking()` are not left in a permanent "thinking" state.
- Ctrl+C with only an orphan thinking box (no running handler) now clears the box without also exiting the app. Previously the same keypress finished the boxes and then fell through to `app.exit()`.
- `_user_cancelled_handler` flag is now reset in `finally` so it can't stay sticky when a handler suppresses `CancelledError` or cancellation races with natural completion. Prevents a leftover `True` state from swallowing a later outer cancellation and stalling shutdown.
- `TextItem(password=True)` now masks input during editing, matching the masking already applied in view mode (previously the secret was visible while typing).
- `DialogConfig.width` is now actually applied to the rendered dialog (was a public field that `_ConfigBasedDialog` never copied to `BaseDialog.width`).
- `ButtonConfig.style` and `ButtonConfig.focused` are now honored — the configured style wraps each button's window style, and the configured focused button receives initial focus when the dialog opens.
- `_renderable_to_ansi` (and the public `rich_to_ansi`, `StreamingContent.append_rich`, `StreamingContent.set_line_rich`) now ignore `NO_COLOR=1`. These APIs explicitly produce ANSI for the thinking box; honoring `NO_COLOR` at the converter layer silently stripped styling and made tests environment-sensitive.

### Changed

- Demo password fields in `demo_showcase.py` and `settings_dialog_demo.py` now mask API-key values in display output so demos don't print secrets the user just typed.

## [0.3.1] - 2026-04-20

### Added

- Optional `BaseDialog.height` (and `height=` parameter on `SettingsDialog` / `show_settings_dialog()`) for one-shot dialog rendering — when set, the dialog allocates its full height in a single render frame instead of growing line-by-line, and body overflow scrolls within the pane. The value is clamped to `terminal_height - 4`; terminals too small for the minimum viable dialog (12 rows) short-circuit to the dialog's escape result.
- `ThinkingBoxManager.is_expanded` public property.
- CI workflow (`.github/workflows/ci.yml`) running ruff, mypy, and pytest on Python 3.9–3.12 for pushes and PRs to `main` and `develop`.

### Changed

- `SettingControl` is now `Generic[T]` over its concrete `SettingsItem` subclass, exposing subclass-only fields (`options`, `width`, `password`, `edit_width`) to the type checker without runtime casts.
- Public dialog APIs (`yes_no_dialog`, `choice_dialog`, `dropdown_dialog`, `show_settings_dialog`, `prompt_async`) now return precise types instead of leaking `Any`.
- `FormattedTextHistory` storage typed as `List[OneStyleAndTextTuple]`; `append_formatted` accepts any `Iterable`.
- `create_thinking_area` now requires a `ThinkingBoxManager` (the previous `Optional` default was unreachable).

### Fixed

- History rendering no longer shows literal ANSI escape codes (e.g. `^[[34m`) in fullscreen mode. `Display` output methods (`welcome`, `rich`, `markdown`, `code`, `add_rich`, `raw`) now parse ANSI into `FormattedText` fragments before storing in history, matching the console-print path.
- `create_history_window` cursor calculation unpacked 3-tuple fragments as 2-tuples (would crash on any fragment carrying a mouse handler); now handles both shapes and runs in O(N) instead of O(N·M).
- Codebase now passes strict mypy (was 61 errors) and ruff (was 131 errors) against its own declared rules.

### Chore

- Added `types-Pygments` to dev dependencies.
- `.ruff_cache` and `.mypy_cache` added to `.gitignore`; previously tracked `docs/plans` files untracked.

## [0.3.0] - 2026-04-16

### Added

- **Multiple thinking boxes** — `start_thinking()` can be called multiple times to create independent, concurrent boxes
- `ThinkingContext.finish()` method for finishing individual boxes (per-box lifecycle control)
- Box ordering via `order` parameter (higher values position closer to the prompt)
- Per-box `max_lines` configuration
- `ThinkingBoxManager` for managing collections of thinking boxes with thread-safe operations
- `ThinkingHeader` class (renamed from `ThinkingSeparator`) — exported from package
- `demo_multi_box.py` example showing concurrent thinking boxes with task list pattern

### Changed

- `start_thinking()` now returns a `ThinkingContext` with per-box `finish()`, `set_title()`, and content methods
- `start_thinking()` accepts optional `order` and `max_lines` parameters
- `thinking()` context manager accepts `order` and `max_lines` parameters
- `is_thinking` returns True if any box is active
- Ctrl+T expands/collapses all boxes together
- `/tasks` command in demo_showcase now uses multi-box pattern

### Deprecated

- `finish_thinking()` — use `ctx.finish()` on the `ThinkingContext` returned by `start_thinking()`, or use the `thinking()` async context manager

### Fixed

- Fullscreen exit now restores pre-fullscreen expansion state (boxes that were collapsed before entering fullscreen are collapsed again on exit)

## [0.2.5] - 2026-03-08

### Added

- `rich_to_ansi()` public API — convert Rich markup to ANSI strings for use with callback-based `start_thinking()` API
- Rich/ANSI formatted text support in thinking box via `append_rich()` and `set_line_rich()`
- `demo_task_progress.py` example with Rich-styled task progress and in-place status updates
- `/quit` and `/tasks` commands in demo_showcase
- `environment.yml` and `requirements.txt` for conda/pip environment setup

### Changed

- Deduplicated expand-hint and ANSI truncation logic
- `truncate_ansi_to_lines()` now delegates to `truncate_to_lines()` with ANSI reset suffix
- `thinking()` context manager reuses `ThinkingContext` from `start_thinking()` instead of creating a duplicate
- `finish_thinking()` uses return value of `finish()` instead of double-reading content
- `ThinkingContext.set_format` callback typed as `ContentFormat` instead of `str`
- Redundant `set_format("ansi")` calls guarded with idempotent `_ensure_ansi_format()`

### Fixed

- `_rich_to_ansi` now correctly respects terminal width for layout-aware renderables (Panel, Table)

### Docs

- Updated README with v0.2.3–v0.2.4 features: Rich/ANSI content, dynamic titles, `set_status()`, completions params

## [0.2.4] - 2026-02-09

### Added

- `set_status()` method on ThinkingPromptSession — set status bar text at runtime, accepts plain text, FormattedText, or Rich renderables
- `ThinkingContext` class — returned by `thinking()` context manager, combines content accumulation with separator title control
- `ThinkingContext.set_title()` — dynamically update the thinking box separator title during a thinking session
- `StreamingContent.set_line()` — in-place line editing with negative index support for progress bar updates
- `thinking()` and `start_thinking()` accept optional `title=` parameter
- `/thinking` slash command in demo_showcase.py demonstrating dynamic titles and line editing

## [0.2.3] - 2026-01-23

### Added

- `complete_while_typing` parameter for ThinkingPromptSession - shows completions automatically while typing
- `completions_menu_height` parameter for ThinkingPromptSession - controls dropdown menu height and reserved space (default: 5)
- Completion menu styles matching dark terminal theme (dark background, blue selection)
- `completer_demo.py` example showing slash-command autocompletion

### Changed

- Consolidated theme with base colors and shared menu styles
- Added configurable markdown styles with simplified theme
- Refactored SettingControl base class to extract shared methods (`_check_focus`, `_build_setting_row`)

### Fixed

- Completion menu theme now properly matches dark mode
- Suppress brief "Window too small" message on dialog open
- Inline select now stops at boundaries instead of wrapping

## [0.2.2] - 2026-01-21

### Added

- `DropdownItem`/`DropdownControl` - true dropdown with framed, scrollable list in edit mode
- `InlineSelectItem`/`InlineSelectControl` - inline select that cycles with Left/Right keys
- Arrow indicators: DropdownControl shows `▼`, InlineSelectControl shows `◀`/`▶` based on position
- Settings dialog demo in `demo_showcase.py` showcasing all control types
- `description` field on SettingsItem for optional help text below labels
- TextItem in-place editing: Enter to edit value in-place, Enter/Escape to confirm/cancel
- Dialog width control: `width` parameter on BaseDialog and SettingsDialog
- Dialog vertical positioning: `top` parameter on BaseDialog and SettingsDialog
- Settings list styles: indicator, label, value, description with selected states

### Changed

- SettingsDialog now uses clean list with `›` focus indicator and right-aligned values
- Dialog background now uses dark theme (`bg:#2a2a2a`) to match terminal
- Checkbox values display as `true`/`false` text with green/grey styling
- SettingsDialog navigation: Up/Down or Tab/Shift-Tab navigates all elements, Ctrl+S saves
- Removed light background overlay from dialogs (`with_background=False`)

### Fixed

- Dialog styling now consistent with dark terminal themes

## [0.2.1] - 2026-01-17

### Added

- **Settings Dialog** - Form-based dialog for configuring multiple settings:
  - `SettingsDialog` - Form dialog with vertical layout
  - `DropdownItem` - Select from list of options (RadioList)
  - `CheckboxItem` - Boolean toggle
  - `TextItem` - Text input with optional password masking
  - `session.show_settings_dialog(title, items)` - Convenience method
- New exports: `SettingsItem`, `DropdownItem`, `CheckboxItem`, `TextItem`, `SettingsDialog`
- `examples/settings_dialog_demo.py` - Settings dialog demo

## [0.2.0] - 2025-01-15

### Added

- **Dialog system** - Modal dialogs that integrate with the prompt session:
  - `yes_no_dialog(title, text)` - Yes/No confirmation dialog
  - `message_dialog(title, text)` - Simple message with OK button
  - `choice_dialog(title, text, choices)` - Multiple button choices
  - `dropdown_dialog(title, text, options)` - Radio list selection
  - `show_dialog(config)` - Custom dialogs via `DialogConfig` or `BaseDialog`
- New exports: `DialogConfig`, `ButtonConfig`, `BaseDialog`
- `examples/dialog_test.py` - Comprehensive dialog system demo
- Dialog commands in `demo_showcase.py` (confirm, info, action, theme)

### Changed

- Simplified `Display` class internals (refactored for maintainability)
- Smaller welcome message in demo_showcase (reduced padding)

## [0.1.1] - 2025-01-10

### Added

- `ThinkingPromptSession.add_rich()` - Print Rich renderables (Panel, Table, Text, Tree, etc.) to console and history
- `Display.rich()` - Underlying method for rendering Rich objects
- `ThinkingPromptSession.clear()` - Clear terminal screen, history buffer, and re-print welcome message
- `examples/clear_demo.py` - Example demonstrating the clear functionality

### Changed

- `Display.clear()` now clears both terminal screen (via ANSI escape codes) and history buffer
- `Display.welcome()` now delegates to `Display.rich()` for Rich renderables (internal refactor)

### Removed

- `ThinkingPromptSession.clear_history()` - Replaced by `clear()` with improved semantics

### Migration Guide

If you were using `clear_history()`:

```python
# Before (0.1.0)
session.clear_history()  # Cleared history and switched to fullscreen

# After (0.1.1)
session.clear()  # Clears terminal + history, re-prints welcome, stays in prompt mode
```

## [0.1.0] - 2025-01-09

### Added

- Initial release
- `ThinkingPromptSession` - Main class for chat-like prompt interface with thinking box
- `AppInfo` - Configuration for app name, version, welcome message, and animations
- `ThinkingPromptStyles` - Customizable styles for the interface
- Thinking box with expand/collapse functionality
- Optional fullscreen mode with chat history
- Streaming content support via `StreamingContent` class
- Context manager API: `async with session.thinking() as content`
- Output methods: `add_response()`, `add_message()`, `add_error()`, `add_warning()`, `add_success()`, `add_code()`
- Rich markdown rendering support
- Pygments syntax highlighting support
- 9 example scripts demonstrating various features
