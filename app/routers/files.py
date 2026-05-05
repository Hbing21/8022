import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import get_settings

router = APIRouter(prefix="/api/files", tags=["files"])
settings = get_settings()


@router.get("/session/{session_id}/{filename}")
def get_session_file(session_id: str, filename: str):
    safe = os.path.basename(filename)
    if not safe or safe != filename:
        raise HTTPException(400, "非法文件名")
    if "/" in safe or "\\" in safe or ".." in safe:
        raise HTTPException(400, "非法文件名")

    fp = os.path.join(settings.photo_storage_dir, "sessions", session_id, safe)
    if not os.path.isfile(fp):
        raise HTTPException(404, "文件不存在")
    rp = os.path.realpath(fp)
    root = os.path.realpath(os.path.join(settings.photo_storage_dir, "sessions", session_id))
    if not rp.startswith(root + os.sep):
        raise HTTPException(403, "访问被拒绝")

    return FileResponse(rp)
