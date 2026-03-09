"""File upload endpoint — handles images and files attached to chat messages."""

import os
import uuid
import time
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from pydantic import BaseModel

from api.auth import get_current_user_from_token
from db.models import User

router = APIRouter(prefix="/api/chat", tags=["uploads"])

# Upload directory — inside the backend root
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# 10 MB limit per file
MAX_FILE_SIZE = 10 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    # Documents
    ".pdf", ".txt", ".md", ".csv", ".json",
    # Code
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css",
    ".lua", ".rs", ".go", ".java", ".cpp", ".c", ".h",
}


class UploadResult(BaseModel):
    id: str
    filename: str
    url: str
    content_type: str
    size: int


@router.post("/upload", response_model=UploadResult)
async def upload_file(
    file: UploadFile = File(...),
    _user: User = Depends(get_current_user_from_token),
):
    """Upload a file (image or document) to attach to a chat message."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' is not supported. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content) / 1024 / 1024:.1f} MB). Max: {MAX_FILE_SIZE / 1024 / 1024:.0f} MB",
        )

    file_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    safe_name = f"{file_id}{ext}"
    dest = UPLOAD_DIR / safe_name
    dest.write_bytes(content)

    return UploadResult(
        id=file_id,
        filename=file.filename,
        url=f"/uploads/{safe_name}",
        content_type=file.content_type or "application/octet-stream",
        size=len(content),
    )
