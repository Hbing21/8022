import os
import secrets
import shutil
from datetime import datetime, timedelta
from typing import List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_optional_user, require_user
from app.models import CaptureSession, Photo, User
from app.schemas import CaptureStartIn, CaptureStartOut, ClaimIn, PhotoOut

router = APIRouter(prefix="/api/capture", tags=["capture"])
settings = get_settings()


def _session_dir(session_id: str) -> str:
    return os.path.join(settings.photo_storage_dir, "sessions", session_id)


def _storage_session_key(sess: CaptureSession) -> str:
    """磁盘目录优先使用设备端会话名，便于和 robot_photos_raw 对齐。"""
    rs = (sess.robot_session_id or "").strip()
    return rs if rs else sess.id


def _parse_robot_session_time(robot_session_id: str) -> Optional[datetime]:
    """robot session 格式通常为 YYYYMMDD_HHMMSS（本地时间）"""
    if not robot_session_id:
        return None
    try:
        return datetime.strptime(robot_session_id, "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def _authorize_guest_or_owner(
    sess: CaptureSession,
    user: Optional[User],
    guest_token: Optional[str],
) -> None:
    now = datetime.utcnow()
    if sess.owner_user_id:
        if user is None or user.id != sess.owner_user_id:
            raise HTTPException(status_code=403, detail="无权访问该会话（需登录为所有者）")
    else:
        if sess.expires_at and sess.expires_at < now:
            raise HTTPException(status_code=410, detail="游客会话已过期")
        if not guest_token or guest_token != sess.guest_token:
            raise HTTPException(status_code=403, detail="需要有效的游客令牌")


@router.post("/sessions/start", response_model=CaptureStartOut)
def start_session(
    body: CaptureStartIn,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    sess = CaptureSession(
        robot_id=(body.robot_id or "").strip(),
        status="pending",
    )
    if user:
        sess.owner_user_id = user.id
        sess.guest_token = None
        sess.expires_at = None
    else:
        sess.guest_token = secrets.token_urlsafe(24)
        sess.expires_at = datetime.utcnow() + timedelta(hours=settings.guest_session_hours)
    db.add(sess)
    db.commit()
    db.refresh(sess)
    os.makedirs(_session_dir(sess.id), exist_ok=True)
    return CaptureStartOut(
        session_id=sess.id,
        guest_token=sess.guest_token,
        expires_at=sess.expires_at,
    )


@router.post("/sessions/{session_id}/import-from-robot")
def import_from_robot(
    session_id: str,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
    guest_token: Optional[str] = Query(None, description="游客会话令牌"),
):
    sess = db.query(CaptureSession).filter(CaptureSession.id == session_id).first()
    if not sess:
        raise HTTPException(404, "会话不存在")

    now = datetime.utcnow()
    if not sess.owner_user_id and sess.expires_at and sess.expires_at < now:
        raise HTTPException(410, "游客会话已过期")

    _authorize_guest_or_owner(sess, user, guest_token)

    url = f"{settings.robot_origin}/photos"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise HTTPException(502, f"无法读取机器人相册: {e}")

    if not data.get("ok"):
        raise HTTPException(502, f"机器人返回错误: {data.get('msg', data)}")

    robot_session_id = data.get("session") or ""
    items = data.get("photos") or []
    sess.robot_session_id = str(robot_session_id)
    sess.status = "imported"
    parsed_capture_time = _parse_robot_session_time(str(robot_session_id))

    session_root = _session_dir(_storage_session_key(sess))
    db.query(Photo).filter(Photo.session_id == sess.id).delete(synchronize_session=False)

    saved = []

    # 清空旧文件，避免重复 import 叠加
    if os.path.isdir(session_root):
        for fn in os.listdir(session_root):
            try:
                os.unlink(os.path.join(session_root, fn))
            except OSError:
                pass

    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or ""
        rel = item.get("url") or ""
        if not name or not rel:
            continue
        if ".." in name or "/" in name or "\\" in name:
            continue
        abs_url = rel if rel.startswith("http") else f"{settings.robot_origin}{rel}"

        fp = os.path.join(session_root, name)
        try:
            img_resp = requests.get(abs_url, timeout=30)
            img_resp.raise_for_status()
            content = img_resp.content
            os.makedirs(session_root, exist_ok=True)
            with open(fp, "wb") as f:
                f.write(content)
        except Exception as e:
            raise HTTPException(502, f"下载照片失败 {name}: {e}") from e

        pub = f"/api/files/session/{_storage_session_key(sess)}/{name}"
        p = Photo(
            session_id=sess.id,
            owner_user_id=sess.owner_user_id,
            robot_id=sess.robot_id or "",
            file_name=name,
            disk_path=fp,
            public_path=pub,
            # 优先使用设备端会话时间，避免前端出现 UTC 小时偏移
            capture_time=parsed_capture_time or datetime.now(),
            file_size=float(len(content)),
        )
        db.add(p)
        saved.append(name)

    db.commit()
    return {"ok": True, "robot_session_id": sess.robot_session_id, "saved": saved}


@router.get("/sessions/{session_id}/photos", response_model=List[PhotoOut])
def list_session_photos(
    session_id: str,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
    guest_token: Optional[str] = Query(None),
):
    sess = db.query(CaptureSession).filter(CaptureSession.id == session_id).first()
    if not sess:
        raise HTTPException(404, "会话不存在")
    now = datetime.utcnow()
    if not sess.owner_user_id and sess.expires_at and sess.expires_at < now:
        raise HTTPException(410, "游客会话已过期")

    _authorize_guest_or_owner(sess, user, guest_token)

    photos = db.query(Photo).filter(Photo.session_id == session_id).order_by(Photo.capture_time).all()

    outs: List[PhotoOut] = []
    for ph in photos:
        outs.append(
            PhotoOut(
                id=ph.id,
                session_id=ph.session_id,
                owner_user_id=ph.owner_user_id,
                file_name=ph.file_name,
                url=ph.public_path,
                capture_time=ph.capture_time,
            )
        )
    return outs


@router.post("/sessions/{session_id}/claim")
def claim_session(
    session_id: str,
    body: ClaimIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    sess = db.query(CaptureSession).filter(CaptureSession.id == session_id).first()
    if not sess:
        raise HTTPException(404, "会话不存在")
    if sess.owner_user_id:
        raise HTTPException(400, "该会话已绑定用户")

    now = datetime.utcnow()
    if sess.expires_at and sess.expires_at < now:
        raise HTTPException(410, "游客会话已过期，无法领取")

    if body.guest_token != sess.guest_token:
        raise HTTPException(403, "游客令牌错误")

    sess.owner_user_id = user.id
    sess.guest_token = None
    sess.expires_at = None

    db.query(Photo).filter(Photo.session_id == session_id).update(
        {"owner_user_id": user.id},
        synchronize_session=False,
    )

    db.commit()
    return {"ok": True, "owner_user_id": user.id}
