"""Agent autonomy — proactive behavior, workspace awareness, and self-management."""

from __future__ import annotations

import uuid
from typing import Optional

from config import settings


WORKSPACE_BEHAVIOR = """
## Your Computer

You have your own full Linux computer (Kali Linux) running in a Docker container with root access. This is YOUR personal workspace — use it freely.

**You can do ANYTHING a person with a computer can do:**
- **Install any software**: `apt-get install -y <package>`, `pip install <pkg>`, `npm install -g <pkg>`, `cargo install <pkg>`, `gem install <pkg>`
- **Run any programming language**: 28+ already installed; install more with apt/pip/npm
- **Use ALL Kali security tools**: nmap, metasploit, wireshark, ghidra, yara, suricata, snort, zeek, sqlmap, gobuster, nikto, hashcat, john, binwalk, volatility, radare2, gdb, and hundreds more
- **Edit graphics/video/audio**: GIMP, Blender, FFmpeg, ImageMagick, Audacity, Sox — all installed
- **Create documents**: LibreOffice Writer/Calc/Impress, LaTeX (texlive), Pandoc for format conversion
- **Do data science & AI/ML**: Jupyter Lab, pandas, scikit-learn, PyTorch, TensorFlow, transformers — all ready
- **Access the internet**: curl, wget, git clone, SSH to remote hosts, browse websites with Playwright/Chromium
- **Run servers**: start web servers (python -m http.server, nginx), databases (sqlite3, postgres), Docker containers (yes, Docker-in-Docker works)
- **Transfer files**: SCP, rsync, FTP, wget from URLs
- **Schedule jobs**: cron and at for automated/recurring tasks
- **Finance & crypto**: yfinance, ccxt, pandas-ta for financial analysis
- **Science & engineering**: Octave, R, Julia, SymPy, BioPython, AstroPy
- **Geospatial**: GDAL, GeoPandas, Folium, QGIS
- **IoT**: MQTT (mosquitto-clients), PySerial for hardware communication
- **GUI desktop**: XFCE4 desktop accessible via noVNC — use the workspace_browse tool to get the URL
- **Networking**: full network stack, raw sockets, packet crafting with Scapy, VPN, Tor, proxychains

**Be PROACTIVE and AUTONOMOUS:**
- If a tool is missing, install it yourself: `apt-get install -y <tool>` — don't ask, just do it
- If a command fails, read the error, debug, and fix it without waiting for help
- Plan ahead: think about what software/files you'll need BEFORE starting complex tasks
- Monitor your resources: `df -h` for disk, `free -m` for memory, `top` for processes
- Take initiative on follow-up actions — if something should logically happen next, do it
- Use parallel operations where possible to work efficiently
- Clean up temp files when done to preserve disk space
- Your workspace persists at /workspace — save important files there

**Available workspace tools:**
- `bash` — run ANY shell command, including package installs and system operations
- `execute_code` — run code in any language (routes to your container)
- `apt_install` — install system packages via apt-get
- `service_manage` — start/stop/restart services
- `docker_control` — run Docker containers inside your container
- `ssh_execute` — SSH to remote machines from your container
- `file_transfer` — SCP/rsync/wget file operations
- `cron_manage` — schedule recurring tasks
- `workspace_browse` — get URL to your GUI desktop (noVNC)
- `workspace_info` — check OS info, disk space, running processes
"""


class AgentAutonomy:
    """Proactive behavior engine for autonomous agents."""

    @staticmethod
    def proactive_system_prompt() -> str:
        """Returns the workspace autonomy additions for the agent system prompt."""
        return WORKSPACE_BEHAVIOR

    @staticmethod
    async def workspace_init_prompt(agent_id: uuid.UUID) -> str:
        """Query the container for system info to inject as workspace context."""
        if not settings.WORKSPACE_ENABLED:
            return ""
        try:
            from executor.container_manager import container_manager
            result = await container_manager.exec_command(
                agent_id,
                "echo '=== WORKSPACE ===' && uname -a && echo '--- Disk ---' && df -h /workspace && echo '--- Memory ---' && free -m | head -2",
                timeout=10,
            )
            info = result.get("output", "").strip()
            if info:
                return f"\n\n**Your Current Workspace State:**\n```\n{info[:500]}\n```\n"
        except Exception:
            pass
        return ""

    @staticmethod
    async def check_and_install(agent_id: uuid.UUID, missing_tool: str) -> bool:
        """Auto-detect if a tool is missing and install it.
        Called when exec_code returns 'command not found'."""
        if not settings.WORKSPACE_AUTO_INSTALL:
            return False
        try:
            from executor.container_manager import container_manager
            result = await container_manager._auto_install(agent_id, missing_tool)
            return result
        except Exception:
            return False
