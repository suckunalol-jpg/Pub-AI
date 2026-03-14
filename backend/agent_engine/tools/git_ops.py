"""
Git Operations Tool — lets the AI manage git repositories on the user's machine.
Supports status, add, commit, push, pull, log, diff, branch, checkout, clone.
"""

import asyncio
import logging
import os
import subprocess
from typing import TYPE_CHECKING

from agent_engine.tools_base import BaseTool, register_tool

if TYPE_CHECKING:
    from agent_engine.agent import Agent

logger = logging.getLogger(__name__)

# Default working directory for git commands
GIT_CWD = os.getcwd()

# Maximum output length before truncation
MAX_OUTPUT = 15000


async def _run_git(*args: str, cwd: str | None = None, timeout: int = 60) -> str:
    """Run a git command and return combined stdout/stderr."""
    cwd = cwd or GIT_CWD

    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return f"Git command timed out after {timeout}s"

    output = ""
    if stdout:
        output += stdout.decode("utf-8", errors="replace")
    if stderr:
        err = stderr.decode("utf-8", errors="replace").strip()
        if err:
            output += f"\n[stderr]\n{err}"
    if proc.returncode != 0:
        output += f"\n[exit code: {proc.returncode}]"

    # Truncate very long output
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + f"\n... (truncated, {len(output)} total chars)"

    return output.strip() or "(no output)"


@register_tool
class GitOpsTool(BaseTool):
    """Run git operations: status, add, commit, push, pull, log, diff, branch, checkout, clone."""

    name = "git_ops"
    description = (
        "Perform git operations on the user's repository. "
        "Args: action (status|add|commit|push|pull|log|diff|branch|checkout|clone), "
        "message (for commit), branch (for push/checkout/branch create), "
        "files (for add/diff, space-separated or '.' for all), "
        "remote (for push, default 'origin'), "
        "url (for clone), path (for clone destination), "
        "cwd (optional working directory override)."
    )

    async def execute(self) -> str:
        action = self.args.get("action", "").lower().strip()
        message = self.args.get("message", "")
        branch = self.args.get("branch", "")
        files = self.args.get("files", "")
        remote = self.args.get("remote", "origin")
        url = self.args.get("url", "")
        path = self.args.get("path", "")
        cwd = self.args.get("cwd", None)

        if not action:
            return "Error: No action provided. Use: status, add, commit, push, pull, log, diff, branch, checkout, clone."

        handler = getattr(self, f"_action_{action}", None)
        if handler is None:
            return f"Error: Unknown action '{action}'. Valid: status, add, commit, push, pull, log, diff, branch, checkout, clone."

        return await handler(
            message=message, branch=branch, files=files,
            remote=remote, url=url, path=path, cwd=cwd,
        )

    async def _action_status(self, *, cwd, **_) -> str:
        return await _run_git("status", cwd=cwd)

    async def _action_add(self, *, files, cwd, **_) -> str:
        targets = files.split() if files else ["."]
        return await _run_git("add", *targets, cwd=cwd)

    async def _action_commit(self, *, message, cwd, **_) -> str:
        if not message:
            return "Error: commit requires a 'message' argument."
        return await _run_git("commit", "-m", message, cwd=cwd)

    async def _action_push(self, *, remote, branch, cwd, **_) -> str:
        args = ["push", remote]
        if branch:
            args.append(branch)
        return await _run_git(*args, cwd=cwd, timeout=120)

    async def _action_pull(self, *, cwd, **_) -> str:
        return await _run_git("pull", cwd=cwd, timeout=120)

    async def _action_log(self, *, cwd, **_) -> str:
        return await _run_git("log", "--oneline", "-20", cwd=cwd)

    async def _action_diff(self, *, files, cwd, **_) -> str:
        args = ["diff"]
        if files:
            args.extend(files.split())
        return await _run_git(*args, cwd=cwd)

    async def _action_branch(self, *, branch, cwd, **_) -> str:
        if branch:
            return await _run_git("branch", branch, cwd=cwd)
        return await _run_git("branch", cwd=cwd)

    async def _action_checkout(self, *, branch, cwd, **_) -> str:
        if not branch:
            return "Error: checkout requires a 'branch' argument."
        return await _run_git("checkout", branch, cwd=cwd)

    async def _action_clone(self, *, url, path, cwd, **_) -> str:
        if not url:
            return "Error: clone requires a 'url' argument."
        args = ["clone", url]
        if path:
            args.append(path)
        return await _run_git(*args, cwd=cwd, timeout=300)
