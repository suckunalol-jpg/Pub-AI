"""Persistent session management for the CLI."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cli.config import SESSIONS_DIR


class SessionManager:
    """Manages persistent conversation sessions."""

    def __init__(self):
        self.session_id: str = str(uuid.uuid4())[:8]
        self.session_name: str = f"session-{self.session_id}"
        self.messages: list[dict] = []
        self.created_at: str = datetime.now(timezone.utc).isoformat()
        self.model_info: dict = {}

    def add_message(self, role: str, content: str):
        """Record a message in the session."""
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def save(self, name: Optional[str] = None):
        """Save the session to disk."""
        if name:
            self.session_name = name

        data = {
            "session_id": self.session_id,
            "session_name": self.session_name,
            "created_at": self.created_at,
            "model_info": self.model_info,
            "messages": self.messages,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        filepath = SESSIONS_DIR / f"{self.session_name}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def load(self, name: str) -> bool:
        """Load a session from disk. Returns True if found."""
        filepath = SESSIONS_DIR / f"{name}.json"
        if not filepath.exists():
            return False

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.session_id = data.get("session_id", self.session_id)
        self.session_name = data.get("session_name", name)
        self.created_at = data.get("created_at", self.created_at)
        self.model_info = data.get("model_info", {})
        self.messages = data.get("messages", [])
        return True

    @staticmethod
    def list_sessions() -> list[dict]:
        """List all saved sessions."""
        sessions = []
        for filepath in sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sessions.append({
                    "name": filepath.stem,
                    "created_at": data.get("created_at", "unknown"),
                    "messages": len(data.get("messages", [])),
                    "model": data.get("model_info", {}).get("model", "unknown"),
                })
            except (json.JSONDecodeError, IOError):
                continue
        return sessions

    def get_history_summary(self, max_messages: int = 20) -> list[dict]:
        """Get recent messages for display."""
        return self.messages[-max_messages:]
