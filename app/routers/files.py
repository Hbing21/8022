import os
import time
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_optional_user, require_admin
from app.models import CaptureSession, User
from app.security import decode_token

router = APIRouter(prefix="/api/files", tags=["files"])
settings = get_settings()
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_BYTES = 10 * 1024 * 1024


@router.get("/session/{session_id}/{filename}")
def get_session_file(
    session_id: str,
    filename: str,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
    guest_token: Optional[str] = Query(None, description="游客会话令牌"),
    access_token: Optional[str] = Query(None, description="登录用户令牌（用于图片直链）"),
):
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

    sess = (
        db.query(CaptureSession)
        .filter((CaptureSession.id == session_id) | (CaptureSession.robot_session_id == session_id))
        .first()
    )
    if not sess:
        raise HTTPException(404, "会话不存在")

    now = datetime.utcnow()
    if sess.owner_user_id:
        if user is None and access_token:
            payload = decode_token(access_token)
            uid = payload.get("sub") if payload else None
            if uid:
                user = db.query(User).filter(User.id == uid).first()
        if user is None:
            raise HTTPException(401, "请先登录后领取/下载")
        if user.id != sess.owner_user_id:
            raise HTTPException(403, "无权访问该会话文件")
    else:
        if sess.expires_at and sess.expires_at < now:
            raise HTTPException(403, "游客会话已过期")
        if not guest_token or guest_token != sess.guest_token:
            raise HTTPException(401, "请先登录后领取/下载")

    return FileResponse(rp)


@router.post("/upload")
async def upload_recommend_image(
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
):
    del admin
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, "仅支持 jpg/jpeg/png/webp 图片")
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(400, "仅支持图片上传")

    data = await file.read()
    if not data:
        raise HTTPException(400, "上传文件为空")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "文件过大，最大 10MB")

    date_dir = time.strftime("%Y%m%d")
    save_dir = os.path.join(settings.photo_storage_dir, "recommends", date_dir)
    os.makedirs(save_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(save_dir, filename)
    with open(file_path, "wb") as f:
        f.write(data)

    return {
        "url": f"/api/files/recommends/{date_dir}/{filename}",
        "size": len(data),
        "content_type": content_type,
    }


@router.get("/recommends/{date_dir}/{filename}")
def get_recommend_file(date_dir: str, filename: str):
    if len(date_dir) != 8 or not date_dir.isdigit():
        raise HTTPException(400, "非法目录名")
    safe = os.path.basename(filename)
    if not safe or safe != filename:
        raise HTTPException(400, "非法文件名")
    if "/" in safe or "\\" in safe or ".." in safe:
        raise HTTPException(400, "非法文件名")

    fp = os.path.join(settings.photo_storage_dir, "recommends", date_dir, safe)
    if not os.path.isfile(fp):
        raise HTTPException(404, "文件不存在")
    rp = os.path.realpath(fp)
    root = os.path.realpath(os.path.join(settings.photo_storage_dir, "recommends", date_dir))
    if not rp.startswith(root + os.sep):
        raise HTTPException(403, "访问被拒绝")

    return FileResponse(rp)
