"""
VPN / Proxy Tool — manage VPN connections and proxy configuration within the container.
Supports: connect_vpn, disconnect_vpn, set_proxy, check_ip.
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

MAX_OUTPUT = 15000


async def _run_cmd(*args: str, timeout: int = 30) -> str:
    """Run a shell command and return combined output."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
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

    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + f"\n... (truncated)"

    return output.strip() or "(no output)"


@register_tool
class VpnProxyTool(BaseTool):
    """Manage VPN connections and proxy settings."""

    name = "vpn_proxy"
    description = (
        "Manage VPN and proxy connections. "
        "Args: action (connect_vpn|disconnect_vpn|set_proxy|check_ip), "
        "config_file (path to .ovpn file for connect_vpn), "
        "auth_file (optional, path to auth credentials file for connect_vpn), "
        "proxy_type (socks4|socks5|http for set_proxy), "
        "proxy_host (host for set_proxy), "
        "proxy_port (port for set_proxy)."
    )

    async def execute(self) -> str:
        action = self.args.get("action", "").lower().strip()

        if not action:
            return "Error: No action provided. Use: connect_vpn, disconnect_vpn, set_proxy, check_ip."

        handler = getattr(self, f"_action_{action}", None)
        if handler is None:
            return f"Error: Unknown action '{action}'. Valid: connect_vpn, disconnect_vpn, set_proxy, check_ip."

        return await handler()

    async def _action_connect_vpn(self) -> str:
        """Start OpenVPN with a config file."""
        config_file = self.args.get("config_file", "")
        if not config_file:
            return "Error: connect_vpn requires a 'config_file' argument (path to .ovpn file)."

        if not os.path.isfile(config_file):
            return f"Error: Config file not found: {config_file}"

        cmd = ["openvpn", "--config", config_file, "--daemon", "--log", "/tmp/openvpn.log"]

        auth_file = self.args.get("auth_file", "")
        if auth_file:
            if not os.path.isfile(auth_file):
                return f"Error: Auth file not found: {auth_file}"
            cmd.extend(["--auth-user-pass", auth_file])

        result = await _run_cmd(*cmd, timeout=15)

        # Give OpenVPN a moment to establish, then check
        await asyncio.sleep(3)
        ip_check = await self._action_check_ip()
        return f"OpenVPN started.\n{result}\nCurrent IP: {ip_check}"

    async def _action_disconnect_vpn(self) -> str:
        """Stop all OpenVPN processes."""
        # Try graceful kill first
        if os.name == "nt":
            result = await _run_cmd("taskkill", "/F", "/IM", "openvpn.exe")
        else:
            result = await _run_cmd("killall", "openvpn")
        return f"VPN disconnected.\n{result}"

    async def _action_set_proxy(self) -> str:
        """Configure proxychains with the given proxy."""
        proxy_type = self.args.get("proxy_type", "socks5").lower()
        proxy_host = self.args.get("proxy_host", "")
        proxy_port = self.args.get("proxy_port", "")

        if not proxy_host or not proxy_port:
            return "Error: set_proxy requires 'proxy_host' and 'proxy_port' arguments."

        if proxy_type not in ("socks4", "socks5", "http"):
            return f"Error: Invalid proxy_type '{proxy_type}'. Use: socks4, socks5, http."

        # Write proxychains config
        config_path = "/etc/proxychains.conf"
        config_content = (
            "strict_chain\n"
            "proxy_dns\n"
            "tcp_read_time_out 15000\n"
            "tcp_connect_time_out 8000\n"
            "[ProxyList]\n"
            f"{proxy_type} {proxy_host} {proxy_port}\n"
        )

        try:
            with open(config_path, "w") as f:
                f.write(config_content)
            return f"Proxychains configured: {proxy_type} {proxy_host}:{proxy_port}\nConfig written to {config_path}"
        except PermissionError:
            # Try writing to user-local config
            fallback = os.path.expanduser("~/.proxychains/proxychains.conf")
            os.makedirs(os.path.dirname(fallback), exist_ok=True)
            with open(fallback, "w") as f:
                f.write(config_content)
            return f"Proxychains configured (user-local): {proxy_type} {proxy_host}:{proxy_port}\nConfig written to {fallback}"

    async def _action_check_ip(self) -> str:
        """Check current public IP address."""
        # Try multiple services in case one is down
        for service in ["https://ifconfig.me", "https://api.ipify.org", "https://icanhazip.com"]:
            result = await _run_cmd("curl", "-s", "--max-time", "10", service, timeout=15)
            if "[exit code:" not in result and result != "(no output)":
                return result.strip()
        return "Could not determine public IP (all services failed)."
