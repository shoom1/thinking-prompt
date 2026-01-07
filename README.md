# thinking-prompt

A prompt_toolkit extension that adds a "thinking box" above the prompt for displaying AI thinking/processing content with real-time streaming updates.

## Features

- **Thinking Box**: A collapsible area above the prompt that shows processing/thinking content
- **Real-time Streaming**: Content updates in real-time as your callback returns new content
- **Fullscreen Mode**: Optional fullscreen mode with chat history (disabled by default)
- **Animated Separator**: Configurable animated indicator showing thinking is in progress
- **Rich Output**: Support for markdown rendering and syntax-highlighted code blocks
- **Customizable Styles**: Full control over colors and styling

## Installation

```bash
pip install thinking-prompt
```

For markdown and code highlighting support:
```bash
pip install thinking-prompt[all]
```

## Quick Start

```python
import asyncio
from thinking_prompt import ThinkingPromptSession, AppInfo

async def main():
    app_info = AppInfo(name="MyApp", version="1.0.0")
    session = ThinkingPromptSession(app_info=app_info, message=">>> ")

    @session.on_input
    async def handle(text: str):
        if not text.strip():
            return

        # Use context manager for clean thinking management
        async with session.thinking() as content:
            content.append("Processing...\n")
            await asyncio.sleep(0.5)
            content.append("Done!\n")

        session.add_response(f"You said: {text}")

    await session.run_async()

if __name__ == "__main__":
    asyncio.run(main())
```

## Key Bindings

| Key | Action |
|-----|--------|
| Ctrl+T | Expand/collapse thinking box (in prompt mode) |
| Ctrl+E | Toggle fullscreen mode (when enabled) |
| Ctrl+C | Cancel current operation or exit |
| Ctrl+D | Exit application |

## API Reference

### ThinkingPromptSession

The main class for creating a thinking-enabled prompt session.

```python
session = ThinkingPromptSession(
    message=">>> ",              # Prompt message
    app_info=AppInfo(...),       # App metadata and configuration
    max_thinking_height=15,      # Max lines when collapsed
    enable_status_bar=True,      # Show status bar
    echo_input=True,             # Echo user input to console
)
```

### Thinking API

**Context Manager (recommended):**
```python
async with session.thinking() as content:
    content.append("Step 1...\n")
    await asyncio.sleep(0.5)
    content.append("Step 2...\n")
# Automatically finishes when exiting context
```

**Manual control:**
```python
# Start with a content callback
chunks = []
session.start_thinking(lambda: ''.join(chunks))

chunks.append("Processing...\n")
await asyncio.sleep(0.5)

# Finish and optionally echo to console
session.finish_thinking(add_to_history=True, echo_to_console=True)
```

### Output Methods

```python
# Plain text response
session.add_response("Hello, world!")

# Markdown (requires rich)
session.add_response("# Title\n- Item 1\n- Item 2", markdown=True)

# Syntax-highlighted code (requires pygments)
session.add_code("def hello(): return 'world'", language="python")

# Status messages
session.add_success("Operation completed")
session.add_warning("Rate limit approaching")
session.add_error("Connection failed")
session.add_message("system", "Connecting to server...")
```

### AppInfo Configuration

```python
app_info = AppInfo(
    name="MyApp",
    version="1.0.0",
    welcome_message="Welcome to MyApp!",  # Optional custom welcome

    # Key bindings
    fullscreen_key="c-e",        # Ctrl+E for fullscreen
    expand_key="c-t",            # Ctrl+T for expand/collapse

    # Feature flags
    fullscreen_enabled=False,    # Enable fullscreen mode
    echo_thinking=True,          # Echo thinking to console after completion

    # Thinking animation
    thinking_text="Thinking",    # Text in separator
    thinking_animation=("⠋", "⠙", "⠹", ...),  # Animation frames
    thinking_animation_position="before",      # "before" or "after" text
)
```

## Examples

See the `examples/` directory for complete demos:

- `basic.py` - Simple thinking box usage
- `demo.py` - Interactive demo with simulated AI thinking
- `streaming.py` - Character-by-character streaming
- `progress_demo.py` - Progress bar with callback
- `demo_progress_line.py` - In-place progress updates
- `demo_messages_during_thinking.py` - Output messages during thinking
- `demo_animated_separator.py` - Different animation configurations

## License

MIT
