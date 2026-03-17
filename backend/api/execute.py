from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user_from_token
from db.database import get_db
from db.models import ExecutionLog, User
from executor.sandbox import sandbox

router = APIRouter(prefix="/api/execute", tags=["execute"])

SUPPORTED_LANGUAGES = [
    # ── General Purpose ────────────────────────────────
    {"id": "python",      "name": "Python 3",            "extension": ".py",     "category": "general"},
    {"id": "javascript",  "name": "JavaScript (Node.js)","extension": ".js",     "category": "general"},
    {"id": "typescript",  "name": "TypeScript",          "extension": ".ts",     "category": "general"},
    {"id": "go",          "name": "Go",                  "extension": ".go",     "category": "general"},
    {"id": "rust",        "name": "Rust",                "extension": ".rs",     "category": "general"},
    {"id": "java",        "name": "Java",                "extension": ".java",   "category": "general"},
    {"id": "csharp",      "name": "C#",                  "extension": ".cs",     "category": "general"},
    {"id": "cpp",         "name": "C++",                 "extension": ".cpp",    "category": "general"},
    {"id": "c",           "name": "C",                   "extension": ".c",      "category": "general"},
    {"id": "ruby",        "name": "Ruby",                "extension": ".rb",     "category": "general"},
    {"id": "php",         "name": "PHP",                 "extension": ".php",    "category": "general"},
    {"id": "swift",       "name": "Swift",               "extension": ".swift",  "category": "general"},
    {"id": "kotlin",      "name": "Kotlin",              "extension": ".kts",    "category": "general"},
    {"id": "scala",       "name": "Scala",               "extension": ".scala",  "category": "general"},
    {"id": "dart",        "name": "Dart",                "extension": ".dart",   "category": "general"},
    {"id": "groovy",      "name": "Groovy",              "extension": ".groovy", "category": "general"},
    # ── Functional & Scientific ────────────────────────
    {"id": "haskell",     "name": "Haskell",             "extension": ".hs",     "category": "functional"},
    {"id": "elixir",      "name": "Elixir",              "extension": ".exs",    "category": "functional"},
    {"id": "julia",       "name": "Julia",               "extension": ".jl",     "category": "scientific"},
    {"id": "r",           "name": "R",                   "extension": ".R",      "category": "scientific"},
    # ── Scripting & Security ───────────────────────────
    {"id": "bash",        "name": "Bash",                "extension": ".sh",     "category": "scripting"},
    {"id": "powershell",  "name": "PowerShell",          "extension": ".ps1",    "category": "scripting"},
    {"id": "perl",        "name": "Perl",                "extension": ".pl",     "category": "scripting"},
    {"id": "lua",         "name": "Lua 5.1",             "extension": ".lua",    "category": "scripting"},
    {"id": "shell",       "name": "POSIX Shell",         "extension": ".sh",     "category": "scripting"},
    # ── Systems & Low-Level ────────────────────────────
    {"id": "assembly",    "name": "x86_64 Assembly (NASM)", "extension": ".asm", "category": "systems"},
    {"id": "zig",         "name": "Zig",                 "extension": ".zig",    "category": "systems"},
    {"id": "nim",         "name": "Nim",                 "extension": ".nim",    "category": "systems"},
    # ── Security DSLs ───────────────────────────────────
    {"id": "yara",       "name": "YARA Rules",          "extension": ".yar",   "category": "security"},
    {"id": "sigma",      "name": "Sigma Rules",         "extension": ".yml",   "category": "security"},
    {"id": "snort",      "name": "Snort Rules",         "extension": ".rules", "category": "security"},
    {"id": "suricata",   "name": "Suricata Rules",      "extension": ".rules", "category": "security"},
    {"id": "zeek",       "name": "Zeek Script",         "extension": ".zeek",  "category": "security"},
    {"id": "metasploit", "name": "Metasploit RC",       "extension": ".rc",    "category": "security"},
    {"id": "nse",        "name": "Nmap NSE Script",     "extension": ".nse",   "category": "security"},
    {"id": "stix",       "name": "STIX 2.x",            "extension": ".json",  "category": "security"},
    {"id": "oval",       "name": "OVAL XML",            "extension": ".xml",   "category": "security"},
    # ── Data & Web ──────────────────────────────────────
    {"id": "sql",        "name": "SQL (SQLite)",         "extension": ".sql",   "category": "data"},
    {"id": "html",       "name": "HTML",                "extension": ".html",  "category": "web"},
    {"id": "css",        "name": "CSS",                 "extension": ".css",   "category": "web"},
    # ── Science & Engineering ────────────────────────────
    {"id": "octave",     "name": "GNU Octave",          "extension": ".m",     "category": "scientific"},
]


# ---------- Schemas ----------

class ExecuteRequest(BaseModel):
    language: str
    code: str


class ExecuteResponse(BaseModel):
    output: str
    exit_code: int
    duration_ms: int


# ---------- Routes ----------

@router.post("", response_model=ExecuteResponse)
async def execute_code(
    req: ExecuteRequest,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    result = await sandbox.execute(language=req.language, code=req.code)

    # Log execution
    log = ExecutionLog(
        user_id=user.id,
        language=req.language,
        code=req.code,
        output=result["output"],
        exit_code=result["exit_code"],
        duration_ms=result["duration_ms"],
    )
    db.add(log)
    await db.commit()

    return ExecuteResponse(
        output=result["output"],
        exit_code=result["exit_code"],
        duration_ms=result["duration_ms"],
    )


@router.get("/languages")
async def list_languages():
    return SUPPORTED_LANGUAGES
