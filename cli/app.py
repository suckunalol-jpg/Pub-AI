"""Pub-AI Terminal CLI — main REPL loop."""
import asyncio
import sys
import os

# Ensure backend is on path
_backend_dir = os.path.join(os.path.dirname(__file__), '..', 'backend')
sys.path.insert(0, os.path.abspath(_backend_dir))

from cli.config import get_agent_config, get_banner, HISTORY_FILE
from cli.renderer import (
    TerminalRenderer, console, print_banner, print_model_info, print_help,
)
from cli.commands import is_command, handle_command
from cli.history import SessionManager


async def run_agent_turn(agent, user_input: str, renderer: TerminalRenderer):
    """Process one user message through the agent and render output."""
    renderer.reset()
    has_streamed = False
    final_response = ""

    try:
        async for event in agent.process_message(user_input):
            if event.type == "thinking":
                renderer.show_thinking(event.content)

            elif event.type == "response_stream":
                if not has_streamed:
                    renderer.start_streaming()
                    has_streamed = True
                renderer.stream_token(event.content)

            elif event.type == "tool_call":
                renderer.stop_streaming()
                renderer.show_tool_call(
                    event.data.get("tool_name", "unknown"),
                    event.data.get("tool_args", {}),
                )

            elif event.type == "tool_result":
                renderer.show_tool_result(
                    event.data.get("tool_name", "unknown"),
                    event.content,
                )

            elif event.type == "response":
                final_response = event.content
                renderer.stop_streaming()
                if not has_streamed:
                    renderer.show_response(event.content)

            elif event.type == "error":
                renderer.show_error(event.content)

            elif event.type == "done":
                renderer.stop_streaming()

    except KeyboardInterrupt:
        agent.cancel()
        renderer.stop_streaming()
        console.print("\n[yellow]Cancelled.[/yellow]")
    except Exception as e:
        renderer.stop_streaming()
        renderer.show_error(str(e))

    # If we streamed, show the final clean version
    if has_streamed:
        renderer.stop_streaming()
        if final_response and final_response != renderer._streaming_text:
            console.print()
            from rich.markdown import Markdown
            console.print(Markdown(final_response))
            console.print()

    return final_response


async def async_main():
    """Async main loop."""
    from agent_engine.agent import Agent

    # Print banner
    print_banner(get_banner())

    # Initialize agent
    config = get_agent_config()
    agent = Agent(config=config)
    renderer = TerminalRenderer()
    session = SessionManager()

    # Show model info
    model_config = config.chat_model
    print_model_info(model_config.provider, model_config.name)
    session.model_info = {"provider": model_config.provider, "model": model_config.name}

    console.print("  Type [bold blue]/help[/bold blue] for commands, [bold blue]/exit[/bold blue] to quit.\n")

    # Set up input handler — use prompt_toolkit if available, fallback to basic input
    prompt_async = None
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.formatted_text import HTML

        prompt_session = PromptSession(
            history=FileHistory(str(HISTORY_FILE)),
            auto_suggest=AutoSuggestFromHistory(),
            multiline=False,
            enable_history_search=True,
        )

        async def _async_input() -> str:
            return await prompt_session.prompt_async(
                HTML('<b><style fg="ansiblue">pub-ai</style></b> <style fg="ansicyan">></style> '),
            )

        # Test that prompt_toolkit can actually work in this terminal
        prompt_session.app  # noqa — triggers output detection early
        prompt_async = _async_input
    except Exception:
        # prompt_toolkit failed (not a real terminal, import error, etc.)
        pass

    if prompt_async is None:
        # Fallback: run sync input() in a thread so we don't block the event loop
        loop = asyncio.get_event_loop()

        async def _fallback_input() -> str:
            return await loop.run_in_executor(None, lambda: input("pub-ai > "))

        prompt_async = _fallback_input

    # Main REPL loop
    while True:
        try:
            user_input = await prompt_async()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # Handle slash commands
        if is_command(user_input):
            should_continue = await handle_command(user_input, agent, session)
            if not should_continue:
                session.save()
                console.print("[dim]Session saved. Goodbye![/dim]")
                break
            continue

        # Record user message
        session.add_message("user", user_input)

        # Run through the agent
        response = await run_agent_turn(agent, user_input, renderer)

        # Record assistant response
        if response:
            session.add_message("assistant", response)

        # Auto-save periodically
        if len(session.messages) % 10 == 0:
            session.save()


def main():
    """Entry point."""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye![/dim]")


if __name__ == "__main__":
    main()
