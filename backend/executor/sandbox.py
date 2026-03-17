from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import time
from typing import Dict, List, Optional, Tuple

from config import settings

# ──────────────────────────────────────────────────────────────
# Language Registry
# ──────────────────────────────────────────────────────────────

# Interpreted languages: {"cmd": [...], "ext": ".x"}
# Compiled languages:    {"ext": ".x", "compile": [...], "run": [...]}
#   Placeholders in compile/run: {src} {out} {dir}
# Special-cased:         {"ext": ".x", "type": "java"|"asm"}

LANGUAGE_CONFIG = {
    # ── Interpreted ─────────────────────────────────────────
    "python":      {"cmd": ["python3", "-u"], "ext": ".py"},
    "javascript":  {"cmd": ["node"], "ext": ".js"},
    "typescript":  {"cmd": ["npx", "tsx"], "ext": ".ts"},
    "lua":         {"cmd": ["lua"], "ext": ".lua"},
    "ruby":        {"cmd": ["ruby"], "ext": ".rb"},
    "php":         {"cmd": ["php"], "ext": ".php"},
    "perl":        {"cmd": ["perl"], "ext": ".pl"},
    "r":           {"cmd": ["Rscript"], "ext": ".R"},
    "bash":        {"cmd": ["bash"], "ext": ".sh"},
    "powershell":  {"cmd": ["pwsh"], "ext": ".ps1"},
    "shell":       {"cmd": ["sh"], "ext": ".sh"},
    "swift":       {"cmd": ["swift"], "ext": ".swift"},
    "haskell":     {"cmd": ["runhaskell"], "ext": ".hs"},
    "go":          {"cmd": ["go", "run"], "ext": ".go"},
    "kotlin":      {"cmd": ["kotlinc", "-script"], "ext": ".kts"},
    "scala":       {"cmd": ["scala"], "ext": ".scala"},
    "elixir":      {"cmd": ["elixir"], "ext": ".exs"},
    "dart":        {"cmd": ["dart", "run"], "ext": ".dart"},
    "julia":       {"cmd": ["julia"], "ext": ".jl"},
    "groovy":      {"cmd": ["groovy"], "ext": ".groovy"},
    "zig":         {"cmd": ["zig", "run"], "ext": ".zig"},
    "nim":         {"cmd": ["nim", "r", "--hints:off"], "ext": ".nim"},

    # ── Compiled ────────────────────────────────────────────
    "c":        {
        "ext": ".c",
        "compile": ["gcc", "{src}", "-o", "{out}", "-lm", "-lpthread"],
        "run": ["{out}"],
    },
    "cpp":      {
        "ext": ".cpp",
        "compile": ["g++", "{src}", "-o", "{out}", "-lm", "-lstdc++", "-lpthread"],
        "run": ["{out}"],
    },
    "rust":     {
        "ext": ".rs",
        "compile": ["rustc", "{src}", "-o", "{out}"],
        "run": ["{out}"],
    },
    "csharp":   {
        "ext": ".cs",
        "compile": ["mcs", "-out:{out}.exe", "{src}"],
        "run": ["mono", "{out}.exe"],
    },

    # ── Special-cased (custom compile pipelines) ───────────
    "java":     {"ext": ".java", "type": "java"},
    "assembly": {"ext": ".asm", "type": "asm"},
}

# ── Aliases ─────────────────────────────────────────────────
LANGUAGE_ALIASES = {
    "py": "python", "python3": "python",
    "js": "javascript", "node": "javascript",
    "ts": "typescript",
    "rb": "ruby",
    "pl": "perl",
    "sh": "bash", "zsh": "bash",
    "ps1": "powershell", "pwsh": "powershell",
    "c++": "cpp", "cxx": "cpp",
    "rs": "rust",
    "cs": "csharp", "c#": "csharp", "dotnet": "csharp",
    "hs": "haskell",
    "kt": "kotlin", "kts": "kotlin",
    "jl": "julia",
    "asm": "assembly", "nasm": "assembly", "x86": "assembly", "x86_64": "assembly",
    "ex": "elixir", "exs": "elixir",
    "sc": "scala",
}

# ──────────────────────────────────────────────────────────────
# Security: env-var scrubbing (primary protection layer)
# ──────────────────────────────────────────────────────────────

_SENSITIVE_KEYS = {
    "DATABASE_URL", "SECRET_KEY", "HF_API_TOKEN", "REDIS_URL",
    "API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
}


def _safe_env() -> Dict[str, str]:
    """Build an environment dict with sensitive variables stripped.

    This is the primary sandbox security boundary — user code runs in a
    subprocess that never sees database credentials, API keys, or secrets.
    """
    return {
        k: v for k, v in os.environ.items()
        if k.upper() not in _SENSITIVE_KEYS
        and not k.upper().endswith("_SECRET")
        and not k.upper().endswith("_TOKEN")
        and not k.upper().endswith("_API_KEY")
    } | {"PYTHONDONTWRITEBYTECODE": "1"}


# ──────────────────────────────────────────────────────────────
# Sandbox
# ──────────────────────────────────────────────────────────────

class Sandbox:
    """Multi-language code execution with timeouts and env-var sandboxing.

    Security model:
    - Sensitive env vars are stripped from the subprocess environment
    - All execution happens in the system temp directory
    - Configurable timeout prevents runaway processes
    - Output is truncated to prevent memory exhaustion
    """

    @staticmethod
    def _resolve_language(language: str) -> Optional[Tuple[str, dict]]:
        """Resolve a language name (including aliases) to its config."""
        key = language.lower().strip()
        key = LANGUAGE_ALIASES.get(key, key)
        config = LANGUAGE_CONFIG.get(key)
        return (key, config) if config else None

    # ── Main entry point ────────────────────────────────────

    async def execute(self, language: str, code: str, *, agent_id=None) -> Dict:
        # Route to per-agent container if an agent_id is provided
        if agent_id is not None and settings.WORKSPACE_ENABLED:
            from executor.container_manager import container_manager
            return await container_manager.exec_code(agent_id, language, code)

        resolved = self._resolve_language(language)
        if not resolved:
            supported = sorted(set(LANGUAGE_CONFIG.keys()) | set(LANGUAGE_ALIASES.keys()))
            return {
                "output": f"Unsupported language: {language}\nSupported: {', '.join(sorted(LANGUAGE_CONFIG.keys()))}",
                "exit_code": 1,
                "duration_ms": 0,
            }

        lang_key, lang = resolved

        # Route to the right handler
        lang_type = lang.get("type", "")
        if lang_type == "java":
            return await self._execute_java(code)
        elif lang_type == "asm":
            return await self._execute_asm(code)
        elif "compile" in lang:
            return await self._execute_compiled(lang, code)
        else:
            return await self._execute_interpreted(lang, code)

    # ── Interpreted languages ───────────────────────────────

    async def _execute_interpreted(self, lang: dict, code: str) -> Dict:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=lang["ext"], delete=False, encoding="utf-8",
        ) as f:
            f.write(code)
            tmp_path = f.name

        try:
            return await self._run_process(lang["cmd"] + [tmp_path])
        finally:
            self._cleanup(tmp_path)

    # ── Compiled languages (generic) ────────────────────────

    async def _execute_compiled(self, lang: dict, code: str) -> Dict:
        tmp_dir = tempfile.gettempdir()
        src_fd, src_path = tempfile.mkstemp(suffix=lang["ext"], dir=tmp_dir)
        base_path = src_path.rsplit(".", 1)[0]

        with os.fdopen(src_fd, "w", encoding="utf-8") as f:
            f.write(code)

        try:
            # ── Compile ──
            compile_cmd = [
                arg.replace("{src}", src_path)
                   .replace("{out}", base_path)
                   .replace("{dir}", tmp_dir)
                for arg in lang["compile"]
            ]
            result = await self._run_process(compile_cmd, phase="Compilation")
            if result["exit_code"] != 0:
                return result

            # ── Run ──
            run_cmd = [
                arg.replace("{out}", base_path)
                   .replace("{dir}", tmp_dir)
                for arg in lang["run"]
            ]
            return await self._run_process(run_cmd)

        finally:
            for path in [src_path, base_path, base_path + ".exe", base_path + ".o"]:
                self._cleanup(path)

    # ── Java (class name must match filename) ───────────────

    async def _execute_java(self, code: str) -> Dict:
        match = re.search(r"(?:public\s+)?class\s+(\w+)", code)
        class_name = match.group(1) if match else "Main"

        tmp_dir = tempfile.mkdtemp(prefix="pubai_java_")
        src_path = os.path.join(tmp_dir, f"{class_name}.java")

        with open(src_path, "w", encoding="utf-8") as f:
            f.write(code)

        try:
            # Compile
            result = await self._run_process(
                ["javac", src_path], phase="Compilation", cwd=tmp_dir,
            )
            if result["exit_code"] != 0:
                return result

            # Run
            return await self._run_process(
                ["java", "-cp", tmp_dir, class_name], cwd=tmp_dir,
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Assembly (NASM → ld → execute) ──────────────────────

    async def _execute_asm(self, code: str) -> Dict:
        tmp_dir = tempfile.gettempdir()
        src_fd, src_path = tempfile.mkstemp(suffix=".asm", dir=tmp_dir)
        base = src_path.rsplit(".", 1)[0]
        obj_path = base + ".o"
        bin_path = base

        with os.fdopen(src_fd, "w", encoding="utf-8") as f:
            f.write(code)

        try:
            # Assemble
            result = await self._run_process(
                ["nasm", "-f", "elf64", src_path, "-o", obj_path],
                phase="Assembly",
            )
            if result["exit_code"] != 0:
                return result

            # Link
            result = await self._run_process(
                ["ld", obj_path, "-o", bin_path],
                phase="Linking",
            )
            if result["exit_code"] != 0:
                return result

            # Run
            return await self._run_process([bin_path])

        finally:
            for p in [src_path, obj_path, bin_path]:
                self._cleanup(p)

    # ── Shared subprocess runner ────────────────────────────

    async def _run_process(
        self,
        cmd: List[str],
        phase: str = "Execution",
        cwd: Optional[str] = None,
    ) -> Dict:
        """Run a subprocess with timeout, env scrubbing, and output truncation."""
        start = time.perf_counter()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=_safe_env(),
                cwd=cwd or tempfile.gettempdir(),
            )
        except FileNotFoundError:
            runtime = cmd[0]
            return {
                "output": f"{phase} failed: '{runtime}' not found. Install it on the server to enable this language.",
                "exit_code": 127,
                "duration_ms": 0,
            }

        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=settings.EXEC_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {
                "output": f"{phase} timed out after {settings.EXEC_TIMEOUT_SECONDS}s",
                "exit_code": -1,
                "duration_ms": int((time.perf_counter() - start) * 1000),
            }

        duration_ms = int((time.perf_counter() - start) * 1000)
        output = stdout.decode("utf-8", errors="replace")

        if len(output) > settings.EXEC_MAX_OUTPUT_BYTES:
            output = output[: settings.EXEC_MAX_OUTPUT_BYTES] + "\n... (output truncated)"

        rc = proc.returncode or 0
        if rc != 0 and phase != "Execution":
            output = f"{phase} failed:\n{output}"

        return {
            "output": output,
            "exit_code": rc,
            "duration_ms": duration_ms,
        }

    @staticmethod
    def _cleanup(*paths: str) -> None:
        for p in paths:
            try:
                os.unlink(p)
            except OSError:
                pass


sandbox = Sandbox()
