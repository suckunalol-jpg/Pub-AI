"""Slash command registry and handlers."""
import json
import os
from typing import TYPE_CHECKING

from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from cli.renderer import console, print_help
from cli.history import SessionManager

if TYPE_CHECKING:
    from agent_engine.agent import Agent


# Command registry
_commands: dict[str, dict] = {}


def command(name: str, description: str = ""):
    """Decorator to register a slash command."""
    def decorator(func):
        _commands[name] = {"handler": func, "description": description}
        return func
    return decorator


def get_commands() -> dict:
    return _commands


def is_command(text: str) -> bool:
    """Check if input is a slash command."""
    return text.strip().startswith("/")


async def handle_command(
    text: str,
    agent: "Agent",
    session: SessionManager,
) -> bool:
    """Handle a slash command. Returns False if the CLI should exit."""
    parts = text.strip().split(maxsplit=1)
    cmd_name = parts[0].lower()
    cmd_args = parts[1] if len(parts) > 1 else ""

    if cmd_name in ("/exit", "/quit"):
        return False

    if cmd_name == "/help":
        print_help()
        return True

    if cmd_name == "/clear":
        agent.reset()
        session.messages.clear()
        console.print("[bold green]Conversation cleared.[/bold green]")
        return True

    if cmd_name == "/model":
        await _handle_model(cmd_args, agent)
        return True

    if cmd_name == "/memory":
        _handle_memory()
        return True

    if cmd_name == "/skills":
        _handle_skills()
        return True

    if cmd_name == "/history":
        _handle_history(session)
        return True

    if cmd_name == "/save":
        session.save(cmd_args.strip() or None)
        console.print(f"[bold green]Session saved as '{session.session_name}'[/bold green]")
        return True

    if cmd_name == "/load":
        if not cmd_args.strip():
            console.print("[yellow]Usage: /load <session_name>[/yellow]")
            return True
        if session.load(cmd_args.strip()):
            # Replay history into agent
            agent.reset()
            for msg in session.messages:
                agent.history.add(msg["role"], msg["content"])
            console.print(f"[bold green]Session '{cmd_args.strip()}' loaded ({len(session.messages)} messages)[/bold green]")
        else:
            console.print(f"[red]Session '{cmd_args.strip()}' not found[/red]")
        return True

    if cmd_name == "/sessions":
        _handle_sessions()
        return True

    if cmd_name == "/system":
        _handle_system(cmd_args, agent)
        return True

    if cmd_name == "/tools":
        _handle_tools()
        return True

    console.print(f"[red]Unknown command: {cmd_name}[/red]  Type /help for available commands.")
    return True


async def _handle_model(args: str, agent: "Agent"):
    """Show or switch model."""
    if not args.strip():
        config = agent.config.chat_model
        console.print(f"[bold]Provider:[/bold] {config.provider}")
        console.print(f"[bold]Model:[/bold] {config.name}")
        console.print(f"[bold]API Base:[/bold] {config.api_base or '(default)'}")
        console.print(f"[bold]Context:[/bold] {config.ctx_length}")
        return

    # Parse model switch: /model provider/name or /model name
    new_model = args.strip()
    if "/" in new_model:
        provider, name = new_model.split("/", 1)
    else:
        provider = agent.config.chat_model.provider
        name = new_model

    agent.config.chat_model.provider = provider
    agent.config.chat_model.name = name

    # Rebuild the chat model with new config
    from agent_engine.models import get_chat_model
    agent.chat_model = get_chat_model(agent.config.chat_model)

    console.print(f"[bold green]Switched to {provider}/{name}[/bold green]")


def _handle_memory():
    """Display saved memories."""
    from agent_engine.tools.memory_tools import _load_memories

    memories = _load_memories()
    if not memories:
        console.print("[dim]No memories saved yet.[/dim]")
        return

    table = Table(title="Memories", show_header=True, header_style="bold magenta")
    table.add_column("ID", style="cyan", width=10)
    table.add_column("Area", style="yellow", width=15)
    table.add_column("Content", ratio=1)
    table.add_column("Created", style="dim", width=20)

    for mem in memories:
        content = mem["text"]
        if len(content) > 100:
            content = content[:100] + "..."
        table.add_row(mem["id"], mem.get("area", "general"), content, mem.get("created_at", ""))

    console.print(table)


def _handle_skills():
    """List available skills."""
    skills_dir = os.path.join(os.getcwd(), "backend", "skills")
    if not os.path.exists(skills_dir):
        # Also check from backend cwd
        skills_dir = os.path.join(os.getcwd(), "skills")

    if not os.path.exists(skills_dir):
        console.print("[dim]No skills directory found. Skills will be created as the agent works.[/dim]")
        return

    skills = []
    for item in os.listdir(skills_dir):
        skill_path = os.path.join(skills_dir, item, "SKILL.md")
        if os.path.isdir(os.path.join(skills_dir, item)) and os.path.exists(skill_path):
            skills.append(item)

    if not skills:
        console.print("[dim]No skills available yet.[/dim]")
        return

    console.print("[bold]Available Skills:[/bold]")
    for s in skills:
        console.print(f"  [cyan]•[/cyan] {s}")


def _handle_history(session: SessionManager):
    """Display conversation history."""
    messages = session.get_history_summary(max_messages=30)
    if not messages:
        console.print("[dim]No conversation history.[/dim]")
        return

    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if len(content) > 200:
            content = content[:200] + "..."

        if role == "user":
            console.print(f"[bold blue]You:[/bold blue] {content}")
        elif role == "assistant":
            console.print(f"[bold green]AI:[/bold green] {content}")
        else:
            console.print(f"[dim][{role}]: {content}[/dim]")
    console.print()


def _handle_sessions():
    """List saved sessions."""
    sessions = SessionManager.list_sessions()
    if not sessions:
        console.print("[dim]No saved sessions.[/dim]")
        return

    table = Table(title="Saved Sessions", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="cyan")
    table.add_column("Messages", justify="right")
    table.add_column("Model", style="dim")
    table.add_column("Created", style="dim")

    for s in sessions[:20]:
        table.add_row(s["name"], str(s["messages"]), s["model"], s["created_at"][:19])

    console.print(table)


def _handle_system(args: str, agent: "Agent"):
    """View or set system prompt."""
    if not args.strip():
        prompt = agent.get_system_prompt()
        if len(prompt) > 1000:
            prompt = prompt[:1000] + "\n... (truncated)"
        console.print(Panel(prompt, title="System Prompt", border_style="magenta"))
        return

    agent.config.system_prompt = args.strip()
    console.print("[bold green]System prompt updated.[/bold green]")


def _handle_tools():
    """List available agent tools."""
    from agent_engine.tools_base import get_all_tools

    tools = get_all_tools()
    table = Table(title="Agent Tools", show_header=True, header_style="bold cyan")
    table.add_column("Tool", style="cyan")
    table.add_column("Description")

    for name, tool_cls in sorted(tools.items()):
        table.add_row(name, tool_cls.description)

    console.print(table)
