"""Rich-based terminal renderer for agent output — with mascot animations."""
import io
import json
import os
import sys
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from rich.spinner import Spinner
from rich.live import Live
from rich.table import Table
from rich.columns import Columns

from cli.mascot import (
    get_mascot_for_tool, get_mascot_for_event, render_mascot,
    IDLE, STARTING, COLOR,
)

# Force UTF-8 on Windows to support unicode characters
if sys.platform == "win32":
    os.system("")  # Enable ANSI escape sequences on Windows
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

console = Console(force_terminal=True)


class TerminalRenderer:
    """Renders agent events to the terminal using Rich."""

    def __init__(self):
        self._streaming_text = ""
        self._live: Live | None = None
        self._tool_count = 0

    def start_streaming(self):
        """Begin a streaming response."""
        self._streaming_text = ""
        self._live = Live(
            Text("", style="dim"),
            console=console,
            refresh_per_second=15,
            transient=True,
        )
        self._live.start()

    def stream_token(self, token: str):
        """Append a token to the streaming display."""
        self._streaming_text += token
        if self._live:
            try:
                self._live.update(Markdown(self._streaming_text))
            except Exception:
                self._live.update(Text(self._streaming_text))

    def stop_streaming(self):
        """Stop streaming and render the final response."""
        if self._live:
            self._live.stop()
            self._live = None

    def show_response(self, text: str):
        """Render a final response."""
        self.stop_streaming()
        if text.strip():
            console.print()
            console.print(Markdown(text))
            console.print()

    def show_tool_call(self, tool_name: str, tool_args: dict):
        """Display a tool invocation with the mascot doing the relevant action."""
        self.stop_streaming()
        self._tool_count += 1

        # Show mascot with emotion for this tool
        label, art = get_mascot_for_tool(tool_name)
        console.print(render_mascot(art, label))

        args_str = json.dumps(tool_args, indent=2, default=str)
        syntax = Syntax(args_str, "json", theme="monokai", line_numbers=False)

        panel = Panel(
            syntax,
            title=f"[bold blue]Tool: {tool_name}[/bold blue]",
            subtitle=f"[dim]call #{self._tool_count}[/dim]",
            border_style="blue",
            padding=(0, 1),
        )
        console.print(panel)

    def show_tool_result(self, tool_name: str, result: str):
        """Display the result of a tool call."""
        display = result
        if len(display) > 2000:
            display = display[:2000] + f"\n... ({len(result)} chars total)"

        panel = Panel(
            Text(display, style="green"),
            title=f"[bold green]Result: {tool_name}[/bold green]",
            border_style="green",
            padding=(0, 1),
        )
        console.print(panel)

    def show_thinking(self, text: str = "Thinking..."):
        """Show thinking indicator with mascot."""
        label, art = get_mascot_for_event("thinking")
        console.print(render_mascot(art, label))

    def show_error(self, message: str):
        """Display an error with mascot."""
        self.stop_streaming()
        label, art = get_mascot_for_event("error")
        console.print(render_mascot(art, label))
        panel = Panel(
            Text(message, style="bold red"),
            title="[bold red]Error[/bold red]",
            border_style="red",
        )
        console.print(panel)

    def show_info(self, message: str):
        """Display an info message."""
        console.print(f"[bold blue]>[/bold blue] {message}")

    def show_success(self, message: str):
        """Display a success message."""
        console.print(f"[bold green]OK[/bold green] {message}")

    def show_warning(self, message: str):
        """Display a warning."""
        console.print(f"[bold yellow]![/bold yellow] {message}")

    def reset(self):
        """Reset renderer state for new conversation turn."""
        self._streaming_text = ""
        self._tool_count = 0
        self.stop_streaming()


def print_banner(banner: str):
    """Print the startup banner with mascot."""
    console.print(Text(banner, style="bold blue"))
    # Show the startup mascot
    console.print(render_mascot(STARTING, "Pub-AI Terminal"))
    console.print()


def print_model_info(provider: str, model_name: str):
    """Print model connection info."""
    console.print(
        f"  [bold]Provider:[/bold] {provider}  "
        f"[bold]Model:[/bold] {model_name}"
    )
    console.print()


def print_help():
    """Print available commands."""
    table = Table(title="Commands", show_header=True, header_style="bold blue")
    table.add_column("Command", style="blue")
    table.add_column("Description")

    commands = [
        ("/help", "Show this help message"),
        ("/clear", "Clear conversation and reset agent"),
        ("/exit, /quit", "Exit the CLI"),
        ("/model [name]", "Show or switch the active model"),
        ("/memory", "Show saved memories"),
        ("/skills", "List available skills"),
        ("/history", "Show conversation history"),
        ("/save [name]", "Save the current session"),
        ("/load [name]", "Load a saved session"),
        ("/system [prompt]", "View or update the system prompt"),
        ("/tools", "List available agent tools"),
        ("/sessions", "List saved sessions"),
        ("Ctrl+C", "Cancel current operation"),
        ("Ctrl+D", "Exit"),
    ]
    for cmd, desc in commands:
        table.add_row(cmd, desc)

    console.print(table)
    console.print()
