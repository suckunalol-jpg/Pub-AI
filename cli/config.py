"""CLI configuration and environment setup."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from backend directory
_backend_dir = Path(__file__).resolve().parent.parent / "backend"
load_dotenv(_backend_dir / ".env")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# CLI home directory for persistent data
CLI_HOME = Path.home() / ".pub-ai"
SESSIONS_DIR = CLI_HOME / "sessions"
HISTORY_FILE = CLI_HOME / "history.txt"
CONFIG_FILE = CLI_HOME / "config.json"

# Ensure directories exist
CLI_HOME.mkdir(exist_ok=True)
SESSIONS_DIR.mkdir(exist_ok=True)


def get_agent_config():
    """Build an AgentConfig from environment variables."""
    from agent_engine.agent import AgentConfig
    from agent_engine.models import default_chat_config, default_utility_config

    return AgentConfig(
        chat_model=default_chat_config(),
        utility_model=default_utility_config(),
    )


def get_banner() -> str:
    """Return the startup banner."""
    return r"""

   ██████╗ ██╗   ██╗██████╗       █████╗ ██╗
   ██╔══██╗██║   ██║██╔══██╗     ██╔══██╗██║
   ██████╔╝██║   ██║██████╔╝     ███████║██║
   ██╔═══╝ ██║   ██║██╔══██╗     ██╔══██║██║
   ██║     ╚██████╔╝██████╔╝     ██║  ██║██║
   ╚═╝      ╚═════╝ ╚═════╝      ╚═╝  ╚═╝╚═╝

   The AI that actually does things.
"""
