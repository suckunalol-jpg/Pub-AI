"""
Container Tool — gives the AI its own persistent sandbox computer.
A Docker container that persists across tool calls, with its own filesystem,
installed packages, running processes, etc. Like Claude Code's sandbox.
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

CONTAINER_NAME = os.getenv("CONTAINER_NAME", "pub-ai-sandbox")
CONTAINER_IMAGE = os.getenv("CONTAINER_IMAGE", "python:3.11-slim")
CONTAINER_NETWORK = os.getenv("CONTAINER_NETWORK", "host")  # host, bridge, none

# Shared workspace: mount the user's CWD into the container
HOST_WORKSPACE = os.getcwd()


def _is_kali_image() -> bool:
    """Check if the configured image is a Kali-based image."""
    return "kali" in CONTAINER_IMAGE.lower()


def _docker_available() -> bool:
    """Check if Docker is available."""
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


async def _ensure_container() -> str:
    """Ensure the persistent sandbox container is running. Returns container name."""
    proc = await asyncio.create_subprocess_exec(
        "docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()

    if proc.returncode == 0:
        if b"true" in stdout:
            return CONTAINER_NAME
        # Container exists but stopped — start it
        proc2 = await asyncio.create_subprocess_exec(
            "docker", "start", CONTAINER_NAME,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        await proc2.communicate()
        return CONTAINER_NAME

    # Container doesn't exist — create it with a persistent workspace
    run_args = [
        "docker", "run", "-d",
        "--name", CONTAINER_NAME,
        "-v", f"{HOST_WORKSPACE}:/workspace",
        "-w", "/workspace",
        "--network", CONTAINER_NETWORK,
        CONTAINER_IMAGE,
        "tail", "-f", "/dev/null",  # keep alive
    ]

    proc3 = await asyncio.create_subprocess_exec(
        *run_args,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    stdout, stderr = await proc3.communicate()
    if proc3.returncode != 0:
        raise RuntimeError(f"Failed to create container: {stderr.decode()}")

    # Skip Python-specific setup for Kali images (tools are pre-installed)
    if _is_kali_image():
        logger.info("Kali image detected — skipping Python-specific setup.")
        return CONTAINER_NAME

    # Install common tools inside the container (Python/slim images)
    setup_cmd = (
        "apt-get update -qq && "
        "apt-get install -y -qq curl wget git jq net-tools procps htop nano vim && "
        "pip install --quiet requests httpx beautifulsoup4 pandas numpy flask fastapi uvicorn && "
        "echo 'Pub-AI sandbox ready'"
    )
    proc4 = await asyncio.create_subprocess_exec(
        "docker", "exec", CONTAINER_NAME, "bash", "-c", setup_cmd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    await proc4.communicate()

    return CONTAINER_NAME


async def _exec_in_container(command: str, timeout: int = 120) -> str:
    """Execute a command inside the sandbox container."""
    container = await _ensure_container()

    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", container, "bash", "-c", command,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return f"Command timed out after {timeout}s"

    output = ""
    if stdout:
        output += stdout.decode("utf-8", errors="replace")
    if stderr:
        err = stderr.decode("utf-8", errors="replace").strip()
        if err:
            output += f"\n[stderr]\n{err}"

    if proc.returncode != 0:
        output += f"\n[exit code: {proc.returncode}]"

    # Truncate
    if len(output) > 15000:
        output = output[:15000] + f"\n... (truncated, {len(output)} total chars)"

    return output.strip() or "(no output)"


@register_tool
class ContainerShellTool(BaseTool):
    """Run a shell command in the persistent sandbox container."""

    name = "container_shell"
    description = (
        "Run a shell command inside your persistent sandbox container (a full Linux computer). "
        "The container has Python, Node.js, git, curl, pip, and a shared /workspace directory. "
        "Anything you install or create persists across calls. "
        "Args: command (the shell command to run), timeout (optional, seconds, default 120)."
    )

    async def execute(self) -> str:
        command = self.args.get("command", "")
        timeout = int(self.args.get("timeout", 120))

        if not command:
            return "Error: No command provided."

        if not _docker_available():
            # Fallback to local execution if Docker isn't available
            return await self._fallback_local(command, timeout)

        try:
            return await _exec_in_container(command, timeout)
        except Exception as e:
            logger.error(f"Container exec error: {e}")
            return f"Container error: {str(e)}. Falling back to local execution."

    async def _fallback_local(self, command: str, timeout: int) -> str:
        """Fallback: run locally if Docker is not available."""
        try:
            if os.name == "nt":
                cmd = ["powershell", "-Command", command]
            else:
                cmd = ["bash", "-c", command]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=os.getcwd(),
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return f"Timed out after {timeout}s"

            output = ""
            if stdout:
                output += stdout.decode("utf-8", errors="replace")
            if stderr:
                err = stderr.decode("utf-8", errors="replace").strip()
                if err:
                    output += f"\n[stderr]\n{err}"
            if proc.returncode != 0:
                output += f"\n[exit code: {proc.returncode}]"
            return output.strip() or "(no output)"
        except Exception as e:
            return f"Local exec error: {str(e)}"


@register_tool
class ContainerPythonTool(BaseTool):
    """Run Python code in the persistent sandbox container."""

    name = "container_python"
    description = (
        "Run Python code inside your persistent sandbox container. "
        "Has access to pip-installed packages (requests, pandas, numpy, etc). "
        "Args: code (Python code to execute)."
    )

    async def execute(self) -> str:
        code = self.args.get("code", "")
        if not code:
            return "Error: No code provided."

        if not _docker_available():
            # Fallback
            try:
                proc = await asyncio.create_subprocess_exec(
                    "python", "-c", code,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
                output = ""
                if stdout:
                    output += stdout.decode("utf-8", errors="replace")
                if stderr:
                    output += f"\n[stderr]\n{stderr.decode('utf-8', errors='replace')}"
                return output.strip() or "(no output)"
            except Exception as e:
                return f"Error: {e}"

        # Escape single quotes in the code for bash
        escaped = code.replace("'", "'\\''")
        return await _exec_in_container(f"python3 -c '{escaped}'")


@register_tool
class ContainerInstallTool(BaseTool):
    """Install packages in the sandbox container."""

    name = "container_install"
    description = (
        "Install packages in the sandbox container using pip or apt. "
        "Args: packages (space-separated package names), manager ('pip' or 'apt', default 'pip')."
    )

    async def execute(self) -> str:
        packages = self.args.get("packages", "")
        manager = self.args.get("manager", "pip").lower()

        if not packages:
            return "Error: No packages specified."

        if not _docker_available():
            return "Docker not available. Install packages locally with pip/apt."

        if manager == "apt":
            cmd = f"apt-get install -y -qq {packages}"
        else:
            cmd = f"pip install --quiet {packages}"

        return await _exec_in_container(cmd)


@register_tool
class ContainerDownloadTool(BaseTool):
    """Download files from URLs into the container workspace."""

    name = "container_download"
    description = (
        "Download a file from a URL into the container's /workspace directory. "
        "Args: url (the URL to download from), filename (optional, output filename), "
        "destination (optional, path inside container, default '/workspace')."
    )

    async def execute(self) -> str:
        url = self.args.get("url", "")
        if not url:
            return "Error: No URL provided."

        filename = self.args.get("filename", "")
        destination = self.args.get("destination", "/workspace")

        if not _docker_available():
            return "Docker not available. Cannot download into container."

        if filename:
            cmd = f"wget -q -O '{destination}/{filename}' '{url}' && echo 'Downloaded {filename}'"
        else:
            cmd = f"wget -q -P '{destination}' '{url}' && echo 'Download complete'"

        try:
            return await _exec_in_container(cmd, timeout=300)
        except Exception as e:
            return f"Download failed: {str(e)}"


@register_tool
class ContainerUploadTool(BaseTool):
    """Copy files between host and container using docker cp."""

    name = "container_upload"
    description = (
        "Copy files between the host machine and the sandbox container. "
        "Args: src (source path), dest (destination path), "
        "direction ('to_container' or 'from_container', default 'to_container')."
    )

    async def execute(self) -> str:
        src = self.args.get("src", "")
        dest = self.args.get("dest", "")
        direction = self.args.get("direction", "to_container")

        if not src or not dest:
            return "Error: Both 'src' and 'dest' are required."

        if not _docker_available():
            return "Docker not available."

        try:
            container = await _ensure_container()

            if direction == "to_container":
                docker_src = src
                docker_dest = f"{container}:{dest}"
            else:
                docker_src = f"{container}:{src}"
                docker_dest = dest

            proc = await asyncio.create_subprocess_exec(
                "docker", "cp", docker_src, docker_dest,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return f"Copy failed: {stderr.decode('utf-8', errors='replace')}"

            return f"Copied {'to' if direction == 'to_container' else 'from'} container: {src} -> {dest}"
        except Exception as e:
            return f"Copy error: {str(e)}"
