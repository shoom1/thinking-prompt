# The README's demo GIF: a scripted run of demo_showcase.py, recorded by VHS
# (https://github.com/charmbracelet/vhs, `brew install vhs`).
#
# From the repo root, with `python` the env thinking_prompt is installed in:
#     vhs examples/demo.tape
# writes img/demo.gif.

Output img/demo.gif

Set Shell bash
# A 100x38 terminal: GitHub scales a README image to its column (~850 px),
# so fewer columns show bigger text.
Set FontFamily "Menlo"
Set FontSize 15
Set LineHeight 1.3
Set Width 1050
Set Height 915
Set Padding 10
Set Framerate 25
Set TypingSpeed 60ms
Set WaitTimeout 30s
# Waits read the cursor's line (Wait+Line): once the output scrolls, VHS 0.12
# reads Wait+Screen from the top of the scrollback, not the screen. The
# thinking runs keep the cursor on the prompt, so they get sleeps, sized from
# the demo's own.
Set Theme { "name": "demo", "black": "#000000", "red": "#c80000", "green": "#00c800", "yellow": "#bfbf00", "blue": "#0000da", "magenta": "#c800c8", "cyan": "#00c4d4", "white": "#e7e7e7", "brightBlack": "#505050", "brightRed": "#ff0000", "brightGreen": "#00ff00", "brightYellow": "#e6e600", "brightBlue": "#0000ff", "brightMagenta": "#ff00ff", "brightCyan": "#00fdfd", "brightWhite": "#f9f9f9", "background": "#1e1e1e", "foreground": "#ffffff", "selection": "#444444", "cursor": "#ffffff" }

# A shell that sets NO_COLOR would record the demo without colour.
Hide
Type "unset NO_COLOR && clear"
Enter
Show

Type "python examples/demo_showcase.py"
Sleep 500ms
Enter
Wait+Line />>>/
Sleep 2.5s

# A message: the thinking box, its progress line and the status bar.
Type "Test query"
Sleep 500ms
Enter
Sleep 8.5s

# The slash-command menu, then several thinking boxes at once.
Type "/"
Sleep 1.5s
Type "tasks"
Sleep 500ms
Enter
Sleep 7.5s

# An inline settings dialog: one cursor walks the rows; 1 runs Save.
Type "/settings"
Sleep 500ms
Enter
Wait+Line /Theme/
Sleep 1.5s
# Theme: open the dropdown's menu and pick the next option.
Enter
Sleep 1s
Down
Sleep 600ms
Enter
Sleep 800ms
# Font Size: step the selector on.
Down
Sleep 500ms
Right
Sleep 500ms
Right
Sleep 800ms
# Username: edit in place.
Down
Sleep 500ms
Enter
Sleep 400ms
Backspace 5
Type "Ada"
Sleep 400ms
Enter
Sleep 800ms
# Auto Save: toggle it on.
Down 3
Sleep 500ms
Space
Sleep 800ms
# Response Style: walk to Detailed and pick it.
Down 2
Sleep 500ms
Enter
Sleep 1s
Type "1"
Wait+Line />>>/
Sleep 2.5s

# The same dialogs drawn as boxes.
Type "/inline"
Sleep 500ms
Enter
Sleep 1.5s

Type "/tools"
Sleep 500ms
Enter
Wait+Line /Web search/
Sleep 1.5s
Down
Sleep 500ms
Space
Sleep 600ms
Down
Sleep 500ms
Space
Sleep 800ms
Tab
Sleep 600ms
Enter
Wait+Line />>>/
Sleep 3s

Ctrl+D
Sleep 1s
