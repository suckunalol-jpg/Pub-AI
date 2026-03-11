"""
Code Execution Tool — adapted from Agent Zero's code_execution_tool.py.
Runs Python, Node.js, or terminal commands locally via subprocess.
For Docker execution, uses paramiko SSH when configured.
"""

import asyncio
import subprocess
import logging
import os
import shlex
from typing import TYPE_CHECKING

from agent_engine.tools_base import BaseTool, register_tool

if TYPE_CHECKING:
    from agent_engine.agent import Agent

logger = logging.getLogger(__name__)


@register_tool
class CodeExecutionTool(BaseTool):
    """Execute code or terminal commands. Supports Python, Node.js, and shell."""

    name = "code_execution"
    description = (
        "Execute code or terminal commands. "
        "Args: runtime (python|nodejs|terminal), code (the code/command to run). "
        "Returns the stdout/stderr output."
    )

    async def execute(self) -> str:
        runtime = self.args.get("runtime", "python").lower().strip()
        code = self.args.get("code", "")

        if not code:
            return "Error: No code provided."

        use_docker = os.getenv("DOCKER_SANDBOX", "false").lower() == "true"

        if use_docker:
            return await self._run_in_docker(runtime, code)

        if runtime == "python":
            return await self._run_python(code)
        elif runtime == "nodejs":
            return await self._run_nodejs(code)
        elif runtime == "terminal":
            return await self._run_terminal(code)
        else:
            return f"Error: Unknown runtime '{runtime}'. Use python, nodejs, or terminal."

    async def _run_in_docker(self, runtime: str, code: str) -> str:
        """Run code inside a sandboxed Docker container."""
        try:
            import docker
            client = docker.from_env()
        except Exception as e:
            return f"Error: Docker sandbox is enabled but Docker is not accessible. Details: {str(e)}"

        container_name = "pub_ai_sandbox"
        try:
            container = client.containers.get(container_name)
            if container.status != "running":
                container.start()
        except docker.errors.NotFound:
            try:
                # Start a persistent sandbox container
                container = client.containers.run(
                    "python:3.11-slim",
                    "tail -f /dev/null",  # keep alive
                    name=container_name,
                    detach=True,
                    network_mode="bridge"
                )
            except Exception as e:
                return f"Error creating sandbox container: {str(e)}"

        # Prepare the command for Docker
        if runtime == "python":
            cmd = ["python", "-c", code]
        elif runtime == "nodejs":
            return "Error: Node.js is not installed in the default sandbox container yet."
        elif runtime == "terminal":
            cmd = ["bash", "-c", code]
        else:
            return f"Error: Unknown runtime '{runtime}'."

        try:
            # Run the command with timeout via asyncio loop to not block
            loop = asyncio.get_running_loop()
            
            def run_cmd():
                return container.exec_run(cmd, workdir="/tmp")

            # Run in a separate thread so we can await it
            exec_result = await loop.run_in_executor(None, run_cmd)

            # Check if it succeeded
            output_str = exec_result.output.decode("utf-8", errors="replace")

            if exec_result.exit_code != 0:
                output_str += f"\n[exit code: {exec_result.exit_code}]"

            max_len = 10000
            if len(output_str) > max_len:
                output_str = output_str[:max_len] + f"\n\n... (output truncated, {len(output_str)} total chars)"

            return output_str.strip() or "(no output)"
        except Exception as e:
            return f"Docker execution error: {str(e)}"

    async def _run_python(self, code: str) -> str:
        """Execute Python code via subprocess."""
        return await self._run_subprocess(["python", "-c", code], label="python")

    async def _run_nodejs(self, code: str) -> str:
        """Execute Node.js code via subprocess."""
        return await self._run_subprocess(["node", "-e", code], label="nodejs")

    async def _run_terminal(self, command: str) -> str:
        """Execute a shell command."""
        if os.name == "nt":
            # Windows: use PowerShell
            return await self._run_subprocess(
                ["powershell", "-Command", command], label="terminal"
            )
        else:
            # Unix: use bash
            return await self._run_subprocess(
                ["bash", "-c", command], label="terminal"
            )

    async def _run_subprocess(
        self,
        cmd: list[str],
        label: str = "exec",
        timeout: int = 120,
    ) -> str:
        """Run a subprocess and capture output."""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.getcwd(),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                return f"Execution timed out after {timeout} seconds."

            output = ""
            if stdout:
                output += stdout.decode("utf-8", errors="replace")
            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():
                    output += f"\n[stderr]\n{stderr_text}"

            if process.returncode != 0:
                output += f"\n[exit code: {process.returncode}]"

            # Truncate very long outputs
            max_len = 10000
            if len(output) > max_len:
                output = output[:max_len] + f"\n\n... (output truncated, {len(output)} total chars)"

            return output.strip() or "(no output)"

        except FileNotFoundError:
            return f"Error: '{cmd[0]}' not found. Make sure it is installed."
        except Exception as e:
            return f"Execution error: {str(e)}"
