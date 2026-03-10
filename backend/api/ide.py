"""IDE API — file management, Git operations, and shell execution.

Each user gets an isolated workspace at workspaces/{user_id}/.
"""

import os
import json
import asyncio
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import get_current_user_from_token
from db.models import User

router = APIRouter(prefix="/api/ide", tags=["ide"])

# Root directory for user workspaces
WORKSPACES_ROOT = Path(__file__).resolve().parent.parent / "workspaces"
WORKSPACES_ROOT.mkdir(exist_ok=True)


def _user_workspace(user: User) -> Path:
    """Get or create the workspace directory for a user."""
    ws = WORKSPACES_ROOT / str(user.id)
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def _safe_path(ws: Path, relative: str) -> Path:
    """Resolve a relative path within the workspace, preventing directory traversal."""
    resolved = (ws / relative).resolve()
    if not str(resolved).startswith(str(ws.resolve())):
        raise HTTPException(status_code=400, detail="Path escape attempt blocked")
    return resolved


# ---------- Schemas ----------

class FileEntry(BaseModel):
    name: str
    path: str
    type: str  # "file" or "directory"
    size: int = 0
    extension: str = ""


class FileContent(BaseModel):
    path: str
    content: str
    language: str = ""


class SaveFileRequest(BaseModel):
    path: str
    content: str


class RenameRequest(BaseModel):
    old_path: str
    new_path: str


class FolderRequest(BaseModel):
    path: str


class GitCloneRequest(BaseModel):
    url: str
    folder: Optional[str] = None


class GitCommitRequest(BaseModel):
    message: str


class ShellRequest(BaseModel):
    command: str
    cwd: Optional[str] = None


# ---------- File Management ----------

@router.get("/files", response_model=List[FileEntry])
async def list_files(
    path: str = Query("", description="Relative path within workspace"),
    user: User = Depends(get_current_user_from_token),
):
    """List directory contents."""
    ws = _user_workspace(user)
    target = _safe_path(ws, path) if path else ws

    if not target.exists():
        return []

    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    entries = []
    try:
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if item.name.startswith(".") and item.name not in (".gitignore",):
                continue  # Skip hidden files except .gitignore
            rel = str(item.relative_to(ws)).replace("\\", "/")
            entry = FileEntry(
                name=item.name,
                path=rel,
                type="directory" if item.is_dir() else "file",
                size=item.stat().st_size if item.is_file() else 0,
                extension=item.suffix if item.is_file() else "",
            )
            entries.append(entry)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    return entries


@router.get("/file")
async def read_file(
    path: str = Query(..., description="Relative path to file"),
    user: User = Depends(get_current_user_from_token),
):
    """Read file content."""
    ws = _user_workspace(user)
    target = _safe_path(ws, path)

    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    # Determine language from extension
    ext_to_lang = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".tsx": "typescriptreact", ".jsx": "javascriptreact",
        ".html": "html", ".css": "css", ".json": "json",
        ".md": "markdown", ".lua": "lua", ".rs": "rust",
        ".go": "go", ".java": "java", ".cpp": "cpp", ".c": "c",
        ".h": "c", ".sh": "shell", ".yaml": "yaml", ".yml": "yaml",
        ".toml": "toml", ".xml": "xml", ".sql": "sql",
        ".txt": "text", ".csv": "text",
    }

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read: {e}")

    return FileContent(
        path=str(target.relative_to(ws)).replace("\\", "/"),
        content=content,
        language=ext_to_lang.get(target.suffix.lower(), "text"),
    )


@router.post("/file")
async def save_file(
    req: SaveFileRequest,
    user: User = Depends(get_current_user_from_token),
):
    """Create or save a file."""
    ws = _user_workspace(user)
    target = _safe_path(ws, req.path)

    # Ensure parent directory exists
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        target.write_text(req.content, encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save: {e}")

    return {"detail": "saved", "path": req.path}


@router.delete("/file")
async def delete_file(
    path: str = Query(...),
    user: User = Depends(get_current_user_from_token),
):
    """Delete a file or directory."""
    ws = _user_workspace(user)
    target = _safe_path(ws, path)

    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")

    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()

    return {"detail": "deleted"}


@router.post("/rename")
async def rename_file(
    req: RenameRequest,
    user: User = Depends(get_current_user_from_token),
):
    """Rename or move a file/directory."""
    ws = _user_workspace(user)
    src = _safe_path(ws, req.old_path)
    dst = _safe_path(ws, req.new_path)

    if not src.exists():
        raise HTTPException(status_code=404, detail="Source not found")

    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)

    return {"detail": "renamed", "new_path": req.new_path}


@router.post("/folder")
async def create_folder(
    req: FolderRequest,
    user: User = Depends(get_current_user_from_token),
):
    """Create a new folder."""
    ws = _user_workspace(user)
    target = _safe_path(ws, req.path)
    target.mkdir(parents=True, exist_ok=True)
    return {"detail": "created", "path": req.path}


# ---------- Git Operations ----------

async def _run_git(ws: Path, *args: str, cwd: Optional[Path] = None) -> dict:
    """Run a git command and return stdout/stderr/exit_code."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=str(cwd or ws),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        return {
            "output": stdout.decode(errors="replace"),
            "error": stderr.decode(errors="replace"),
            "exit_code": proc.returncode or 0,
        }
    except asyncio.TimeoutError:
        return {"output": "", "error": "Git command timed out", "exit_code": 1}
    except FileNotFoundError:
        return {"output": "", "error": "Git is not installed", "exit_code": 1}


@router.post("/git/clone")
async def git_clone(
    req: GitCloneRequest,
    user: User = Depends(get_current_user_from_token),
):
    ws = _user_workspace(user)
    folder = req.folder or req.url.split("/")[-1].replace(".git", "")
    target = _safe_path(ws, folder)

    if target.exists():
        raise HTTPException(status_code=400, detail=f"Directory '{folder}' already exists")

    result = await _run_git(ws, "clone", "--depth=1", req.url, str(target))
    if result["exit_code"] != 0:
        raise HTTPException(status_code=400, detail=result["error"] or "Clone failed")

    return {"detail": "cloned", "folder": folder}


@router.get("/git/status")
async def git_status(
    path: str = Query("", description="Subdirectory (git repo) within workspace"),
    user: User = Depends(get_current_user_from_token),
):
    ws = _user_workspace(user)
    repo = _safe_path(ws, path) if path else ws

    # Get branch
    branch_result = await _run_git(ws, "rev-parse", "--abbrev-ref", "HEAD", cwd=repo)
    # Get status
    status_result = await _run_git(ws, "status", "--porcelain", cwd=repo)

    return {
        "branch": branch_result["output"].strip() if branch_result["exit_code"] == 0 else "unknown",
        "changes": status_result["output"].strip().split("\n") if status_result["output"].strip() else [],
        "is_repo": branch_result["exit_code"] == 0,
    }


@router.get("/git/log")
async def git_log(
    path: str = Query(""),
    user: User = Depends(get_current_user_from_token),
):
    ws = _user_workspace(user)
    repo = _safe_path(ws, path) if path else ws

    result = await _run_git(
        ws, "log", "--oneline", "--no-decorate", "-15", cwd=repo
    )
    if result["exit_code"] != 0:
        return {"commits": []}

    commits = []
    for line in result["output"].strip().split("\n"):
        if line.strip():
            parts = line.split(" ", 1)
            commits.append({"hash": parts[0], "message": parts[1] if len(parts) > 1 else ""})

    return {"commits": commits}


@router.post("/git/commit")
async def git_commit(
    req: GitCommitRequest,
    path: str = Query(""),
    user: User = Depends(get_current_user_from_token),
):
    ws = _user_workspace(user)
    repo = _safe_path(ws, path) if path else ws

    # Stage all changes
    add_result = await _run_git(ws, "add", "-A", cwd=repo)
    if add_result["exit_code"] != 0:
        raise HTTPException(status_code=400, detail=add_result["error"])

    # Commit
    result = await _run_git(ws, "commit", "-m", req.message, cwd=repo)
    return {
        "output": result["output"],
        "exit_code": result["exit_code"],
    }


@router.post("/git/push")
async def git_push(
    path: str = Query(""),
    user: User = Depends(get_current_user_from_token),
):
    ws = _user_workspace(user)
    repo = _safe_path(ws, path) if path else ws

    result = await _run_git(ws, "push", cwd=repo)
    return {
        "output": result["output"] or result["error"],
        "exit_code": result["exit_code"],
    }


# ---------- Shell Execution ----------

# Detect Git Bash on Windows
import platform

def _find_git_bash() -> Optional[str]:
    """Find Git Bash executable on Windows."""
    if platform.system() != "Windows":
        return None
    common_paths = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin\bash.exe"),
    ]
    for p in common_paths:
        if os.path.isfile(p):
            return p
    # Try PATH
    import shutil as _shutil
    bash = _shutil.which("bash")
    if bash and "git" in bash.lower():
        return bash
    return None


GIT_BASH_PATH = _find_git_bash()


@router.get("/shell/info")
async def shell_info(user: User = Depends(get_current_user_from_token)):
    """Return info about the available shell."""
    return {
        "shell": "git-bash" if GIT_BASH_PATH else ("bash" if platform.system() != "Windows" else "cmd"),
        "git_bash_path": GIT_BASH_PATH,
    }


@router.post("/shell")
async def run_shell(
    req: ShellRequest,
    user: User = Depends(get_current_user_from_token),
):
    """Run a shell command within the user's workspace (uses Git Bash on Windows if available)."""
    ws = _user_workspace(user)
    cwd = _safe_path(ws, req.cwd) if req.cwd else ws

    if not cwd.exists():
        cwd = ws

    try:
        if GIT_BASH_PATH:
            # Use Git Bash as the shell on Windows
            proc = await asyncio.create_subprocess_exec(
                GIT_BASH_PATH, "-c", req.command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "HOME": str(ws), "TERM": "xterm-256color"},
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                req.command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "HOME": str(ws), "TERM": "xterm-256color"},
            )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return {
            "output": stdout.decode(errors="replace"),
            "exit_code": proc.returncode or 0,
        }
    except asyncio.TimeoutError:
        return {"output": "Command timed out (30s limit)", "exit_code": 1}
    except Exception as e:
        return {"output": str(e), "exit_code": 1}

