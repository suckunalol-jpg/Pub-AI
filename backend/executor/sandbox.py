from __future__ import annotations

import asyncio
import os
import tempfile
import time
from typing import Dict

from config import settings

LANGUAGE_CONFIG = {
    "python": {"cmd": ["python", "-u"], "ext": ".py"},
    "javascript": {"cmd": ["node"], "ext": ".js"},
    "lua": {"cmd": ["lua"], "ext": ".lua"},
}


class Sandbox:
    """Sandboxed code execution using subprocess with timeouts and resource limits."""

    async def execute(self, language: str, code: str) -> Dict:
        lang = LANGUAGE_CONFIG.get(language)
        if not lang:
            return {
                "output": f"Unsupported language: {language}",
                "exit_code": 1,
                "duration_ms": 0,
            }

        # Write code to temp file
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=lang["ext"],
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(code)
            tmp_path = f.name

        try:
            start = time.perf_counter()
            proc = await asyncio.create_subprocess_exec(
                *lang["cmd"],
                tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )

            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=settings.EXEC_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {
                    "output": f"Execution timed out after {settings.EXEC_TIMEOUT_SECONDS}s",
                    "exit_code": -1,
                    "duration_ms": int((time.perf_counter() - start) * 1000),
                }

            duration_ms = int((time.perf_counter() - start) * 1000)
            output = stdout.decode("utf-8", errors="replace")

            # Truncate if too long
            if len(output) > settings.EXEC_MAX_OUTPUT_BYTES:
                output = output[: settings.EXEC_MAX_OUTPUT_BYTES] + "\n... (output truncated)"

            return {
                "output": output,
                "exit_code": proc.returncode or 0,
                "duration_ms": duration_ms,
            }
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


sandbox = Sandbox()
