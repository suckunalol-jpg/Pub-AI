"""Per-agent Docker container lifecycle manager.

Each agent gets its own long-lived Kali Linux workspace container with a
persistent volume.  Sub-agents may share their parent's container.  A
background reaper task destroys idle containers after the configured timeout.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class WorkspaceContainer:
    """In-memory record of a running workspace container."""

    container_id: str
    container_name: str
    agent_id: uuid.UUID
    user_id: Optional[uuid.UUID]
    status: str  # creating / running / stopped / destroyed
    volume_name: str
    last_activity: datetime = field(default_factory=datetime.utcnow)
    vnc_port: Optional[int] = None


class ContainerManager:
    """Manages per-agent Kali Linux Docker containers."""

    def __init__(self) -> None:
        self._containers: Dict[uuid.UUID, WorkspaceContainer] = {}
        self._docker = None  # lazy init
        self._vnc_port_counter: int = settings.WORKSPACE_VNC_BASE_PORT
        self._lock = asyncio.Lock()

    # ── Docker client (lazy) ─────────────────────────────────

    def _get_docker(self):  # -> docker.DockerClient
        if self._docker is None:
            import docker
            self._docker = docker.from_env()
        return self._docker

    # ── Naming helpers ───────────────────────────────────────

    @staticmethod
    def _container_name(agent_id: uuid.UUID) -> str:
        return f"pubai-ws-{str(agent_id)[:8]}"

    @staticmethod
    def _volume_name(agent_id: uuid.UUID) -> str:
        return f"pubai-vol-{str(agent_id)[:8]}"

    # ── Get or create ────────────────────────────────────────

    async def get_or_create(
        self,
        agent_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        config: Optional[dict] = None,
    ) -> WorkspaceContainer:
        """Get existing container or create a new one for this agent."""
        async with self._lock:
            # Sub-agent inheritance: reuse parent's container
            if config:
                parent_id = config.get("parent_agent_id")
                if parent_id and not config.get("own_container"):
                    parent_uuid = (
                        uuid.UUID(str(parent_id))
                        if not isinstance(parent_id, uuid.UUID)
                        else parent_id
                    )
                    if parent_uuid in self._containers:
                        ws = self._containers[parent_uuid]
                        ws.last_activity = datetime.utcnow()
                        # Register this agent as using the parent's container
                        self._containers[agent_id] = ws
                        return ws

            # Check in-memory registry
            if agent_id in self._containers:
                ws = self._containers[agent_id]
                if ws.status != "destroyed":
                    ws.last_activity = datetime.utcnow()
                    return ws

            # Check if container already running in Docker
            name = self._container_name(agent_id)
            try:
                client = self._get_docker()
                existing = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: client.containers.get(name)
                )
                if existing.status == "running":
                    ws = WorkspaceContainer(
                        container_id=existing.id,
                        container_name=name,
                        agent_id=agent_id,
                        user_id=user_id,
                        status="running",
                        volume_name=self._volume_name(agent_id),
                    )
                    self._containers[agent_id] = ws
                    return ws
            except Exception:
                pass

            # Create new container
            return await self._create_container(agent_id, user_id, config or {})

    # ── Container creation ───────────────────────────────────

    async def _create_container(
        self,
        agent_id: uuid.UUID,
        user_id: Optional[uuid.UUID],
        config: dict,
    ) -> WorkspaceContainer:
        name = self._container_name(agent_id)
        volume_name = self._volume_name(agent_id)
        vnc_port = self._vnc_port_counter
        self._vnc_port_counter += 1

        logger.info("Creating workspace container %s for agent %s", name, agent_id)

        def _run():
            client = self._get_docker()
            # Create named volume for persistence
            try:
                client.volumes.create(name=volume_name)
            except Exception:
                pass  # Already exists

            container = client.containers.run(
                image=settings.WORKSPACE_IMAGE,
                name=name,
                detach=True,
                privileged=settings.WORKSPACE_PRIVILEGED,
                network_mode=settings.WORKSPACE_NETWORK_MODE,
                mem_limit=settings.WORKSPACE_MEMORY_LIMIT,
                nano_cpus=int(settings.WORKSPACE_CPU_LIMIT * 1e9),
                pids_limit=settings.WORKSPACE_PID_LIMIT,
                volumes={
                    volume_name: {"bind": "/workspace", "mode": "rw"},
                    "/var/run/docker.sock": {
                        "bind": "/var/run/docker.sock",
                        "mode": "rw",
                    },
                },
                environment={
                    "DISPLAY": ":99",
                    "AGENT_ID": str(agent_id),
                },
                labels={
                    "pubai.agent_id": str(agent_id),
                    "pubai.workspace": "true",
                },
            )
            return container

        try:
            container = await asyncio.get_event_loop().run_in_executor(None, _run)
        except Exception as e:
            logger.error("Failed to create container for agent %s: %s", agent_id, e)
            raise RuntimeError(f"Container creation failed: {e}") from e

        ws = WorkspaceContainer(
            container_id=container.id,
            container_name=name,
            agent_id=agent_id,
            user_id=user_id,
            status="running",
            volume_name=volume_name,
            vnc_port=vnc_port if settings.WORKSPACE_VNC_ENABLED else None,
        )
        self._containers[agent_id] = ws

        # Start VNC services if enabled
        if settings.WORKSPACE_VNC_ENABLED:
            asyncio.create_task(self._start_vnc(name))

        return ws

    # ── VNC bootstrap ────────────────────────────────────────

    async def _start_vnc(self, container_name: str) -> None:
        """Start Xvfb + x11vnc + noVNC inside the container."""
        try:
            await self._exec_raw(
                container_name,
                "Xvfb :99 -screen 0 1920x1080x24 &"
                " sleep 1 && x11vnc -display :99 -forever -nopw -bg"
                " && /usr/share/novnc/utils/novnc_proxy"
                " --vnc localhost:5900 --listen 6080 &",
                timeout=10,
            )
        except Exception as e:
            logger.debug("VNC start note (non-fatal): %s", e)

    # ── Raw command execution ────────────────────────────────

    async def _exec_raw(
        self, container_name: str, command: str, timeout: int = 120
    ) -> dict:
        """Run a command in the container via ``docker exec``."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", container_name, "bash", "-c", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode("utf-8", errors="replace")
            if len(output) > settings.WORKSPACE_MAX_OUTPUT_BYTES:
                output = (
                    output[: settings.WORKSPACE_MAX_OUTPUT_BYTES] + "\n... (truncated)"
                )
            return {
                "output": output,
                "exit_code": proc.returncode or 0,
                "duration_ms": 0,
            }
        except asyncio.TimeoutError:
            return {
                "output": f"Command timed out after {timeout}s",
                "exit_code": -1,
                "duration_ms": timeout * 1000,
            }
        except FileNotFoundError:
            return {
                "output": (
                    "docker command not found — is Docker installed and in PATH?"
                ),
                "exit_code": 127,
                "duration_ms": 0,
            }

    # ── Public: shell command execution ──────────────────────

    async def exec_command(
        self,
        agent_id: uuid.UUID,
        command: str,
        timeout: Optional[int] = None,
        cwd: Optional[str] = None,
    ) -> dict:
        """Execute a shell command inside the agent's container."""
        ws = await self.get_or_create(agent_id)
        ws.last_activity = datetime.utcnow()

        effective_timeout = timeout or settings.WORKSPACE_EXEC_TIMEOUT
        full_cmd = f"cd {cwd} && {command}" if cwd else command

        start = time.perf_counter()
        result = await self._exec_raw(
            ws.container_name, full_cmd, timeout=effective_timeout
        )
        result["duration_ms"] = int((time.perf_counter() - start) * 1000)
        return result

    # ── Public: language-aware code execution ────────────────

    async def exec_code(
        self,
        agent_id: uuid.UUID,
        language: str,
        code: str,
        timeout: Optional[int] = None,
    ) -> dict:
        """Execute code in the given language inside the agent's container."""
        from executor.container_languages import resolve_container_language

        ws = await self.get_or_create(agent_id)
        ws.last_activity = datetime.utcnow()

        resolved = resolve_container_language(language)
        if not resolved:
            return {
                "output": f"Unsupported language: {language}",
                "exit_code": 1,
                "duration_ms": 0,
            }

        lang_key, lang_cfg = resolved
        lang_type = lang_cfg.get("type", "")

        # ── Static files (HTML / CSS) — write to /workspace ──
        if lang_type == "static":
            ext = lang_cfg["ext"]
            path = f"/workspace/output{ext}"
            await self.upload_file(agent_id, path, code)
            return {
                "output": (
                    f"File written to {path}\n"
                    "Open via workspace browser or noVNC."
                ),
                "exit_code": 0,
                "duration_ms": 0,
            }

        # ── STIX (Python wrapper) ────────────────────────────
        if lang_type == "stix":
            escaped_code = code.replace("\\", "\\\\").replace("'", "\\'")
            code = (
                "import json, sys\n"
                "from stix2 import parse\n"
                "try:\n"
                f"    obj = parse('{escaped_code}', allow_custom=True)\n"
                "    print(obj.serialize(pretty=True))\n"
                "except Exception as e:\n"
                "    print(f'STIX Error: {e}', file=sys.stderr)\n"
                "    sys.exit(1)\n"
            )
            lang_cfg = {"ext": ".py", "cmd": ["python3"]}

        # ── Cypher (Python wrapper) ──────────────────────────
        if lang_type == "cypher":
            preview = code[:200].replace("'", "\\'")
            code = (
                "from neo4j import GraphDatabase\n"
                "# Cypher query — requires running Neo4j on bolt://localhost:7687\n"
                f"print('Cypher: {preview}')\n"
            )
            lang_cfg = {"ext": ".py", "cmd": ["python3"]}

        # ── SQL (piped to sqlite3) ───────────────────────────
        if lang_type == "sql":
            escaped = code.replace("'", "'\\''")
            return await self.exec_command(
                agent_id,
                f"echo '{escaped}' | sqlite3 :memory:",
                timeout=timeout,
            )

        # ── General: write code to temp file and run ─────────
        ext = lang_cfg["ext"]
        remote_path = f"/tmp/pubai_code_{str(agent_id)[:8]}{ext}"

        await self.upload_file(agent_id, remote_path, code)

        # Build run command
        cmd_parts = lang_cfg.get("cmd", [])
        if cmd_parts:
            cmd = " ".join(c.replace("{src}", remote_path) for c in cmd_parts)
        elif "compile" in lang_cfg:
            out_path = remote_path.rsplit(".", 1)[0]
            compile_cmd = " ".join(
                c.replace("{src}", remote_path).replace("{out}", out_path)
                for c in lang_cfg["compile"]
            )
            run_cmd = " ".join(
                c.replace("{out}", out_path) for c in lang_cfg["run"]
            )
            cmd = f"{compile_cmd} && {run_cmd}"
        else:
            return {
                "output": f"No run command for language: {language}",
                "exit_code": 1,
                "duration_ms": 0,
            }

        result = await self.exec_command(agent_id, cmd, timeout=timeout)

        # Auto-install if command not found
        if result["exit_code"] == 127 and settings.WORKSPACE_AUTO_INSTALL:
            installed = await self._auto_install(agent_id, lang_key)
            if installed:
                result = await self.exec_command(agent_id, cmd, timeout=timeout)

        return result

    # ── Auto-install missing runtimes ────────────────────────

    async def _auto_install(self, agent_id: uuid.UUID, lang_key: str) -> bool:
        """Auto-install a missing runtime inside the container."""
        INSTALL_MAP = {
            "julia":      "apt-get install -y julia",
            "swift":      "apt-get install -y swift || true",
            "dart":       "apt-get install -y dart",
            "nim":        "apt-get install -y nim",
            "zig":        "snap install zig --classic --beta"
                          " || apt-get install -y zig || true",
            "kotlin":     "apt-get install -y kotlin",
            "scala":      "apt-get install -y scala",
            "elixir":     "apt-get install -y elixir",
            "groovy":     "apt-get install -y groovy",
            "yara":       "apt-get install -y yara",
            "suricata":   "apt-get install -y suricata",
            "snort":      "apt-get install -y snort",
            "zeek":       "apt-get install -y zeek",
            "metasploit": "apt-get install -y metasploit-framework",
        }
        cmd = INSTALL_MAP.get(lang_key)
        if not cmd:
            return False
        logger.info(
            "Auto-installing %s in container for agent %s", lang_key, agent_id
        )
        result = await self.exec_command(
            agent_id,
            f"DEBIAN_FRONTEND=noninteractive {cmd}",
            timeout=120,
        )
        return result["exit_code"] == 0

    # ── File transfer ────────────────────────────────────────

    async def upload_file(
        self, agent_id: uuid.UUID, dest_path: str, content: str
    ) -> None:
        """Write a file into the container via ``docker exec`` + heredoc."""
        ws = await self.get_or_create(agent_id)
        # Create parent directory if needed
        parent = os.path.dirname(dest_path)
        if parent:
            await self._exec_raw(ws.container_name, f"mkdir -p '{parent}'", timeout=10)
        await self._exec_raw(
            ws.container_name,
            f"cat > '{dest_path}' << 'PUBAI_EOF'\n{content}\nPUBAI_EOF",
            timeout=30,
        )

    async def download_file(self, agent_id: uuid.UUID, path: str) -> bytes:
        """Read a file from the container."""
        ws = await self.get_or_create(agent_id)
        result = await self._exec_raw(ws.container_name, f"cat '{path}'", timeout=30)
        return result["output"].encode("utf-8")

    # ── Container lifecycle ──────────────────────────────────

    async def destroy(self, agent_id: uuid.UUID) -> None:
        """Destroy the container for this agent."""
        ws = self._containers.pop(agent_id, None)
        if not ws or ws.status == "destroyed":
            return

        # Don't destroy if another agent is sharing this container
        sharing = [
            aid
            for aid, w in self._containers.items()
            if w.container_id == ws.container_id
        ]
        if sharing:
            return

        ws.status = "destroyed"
        logger.info("Destroying container %s", ws.container_name)

        def _stop():
            try:
                client = self._get_docker()
                container = client.containers.get(ws.container_name)
                container.stop(timeout=5)
                container.remove(force=True)
            except Exception as e:
                logger.debug("Container destroy note: %s", e)

        await asyncio.get_event_loop().run_in_executor(None, _stop)

    async def cleanup_idle(self, max_idle_minutes: Optional[int] = None) -> int:
        """Destroy containers that have been idle too long."""
        threshold = max_idle_minutes or settings.WORKSPACE_IDLE_TIMEOUT_MINUTES
        cutoff = datetime.utcnow() - timedelta(minutes=threshold)
        idle = [
            aid
            for aid, ws in list(self._containers.items())
            if ws.last_activity < cutoff and ws.status == "running"
        ]
        for aid in idle:
            await self.destroy(aid)
        return len(idle)

    async def cleanup_all(self) -> None:
        """Destroy every tracked container."""
        for aid in list(self._containers.keys()):
            await self.destroy(aid)

    async def run_reaper(self) -> None:
        """Background task: clean up idle containers every 5 minutes."""
        while True:
            await asyncio.sleep(300)
            try:
                cleaned = await self.cleanup_idle()
                if cleaned:
                    logger.info("Reaper: cleaned up %d idle containers", cleaned)
            except Exception as e:
                logger.error("Reaper error: %s", e)

    # ── Introspection helpers ────────────────────────────────

    def get_vnc_url(self, agent_id: uuid.UUID) -> Optional[str]:
        ws = self._containers.get(agent_id)
        if ws and ws.vnc_port:
            return f"http://localhost:{ws.vnc_port}/vnc.html"
        return None

    async def list_containers(self) -> List[dict]:
        return [
            {
                "agent_id": str(ws.agent_id),
                "container_name": ws.container_name,
                "status": ws.status,
                "last_activity": ws.last_activity.isoformat(),
                "vnc_url": self.get_vnc_url(ws.agent_id),
            }
            for ws in self._containers.values()
        ]


# Module-level singleton
container_manager = ContainerManager()
