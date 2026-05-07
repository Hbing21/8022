import os
import shutil
from typing import Set

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import require_user
from app.models import (
    CaptureSession,
    PaymentDailySeq,
    PaymentRecord,
    Photo,
    RecommendLike,
    RecommendSpot,
    RobotConnectHistory,
    User,
)
from app.schemas import DeleteAccountIn, LoginIn, RegisterIn, RegisterOut, TokenOut, UserPublic
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


def _session_dir(session_key: str) -> str:
    return os.path.join(settings.photo_storage_dir, "sessions", session_key)


def _storage_session_key(sess: CaptureSession) -> str:
    rs = (sess.robot_session_id or "").strip()
    return rs if rs else sess.id


def _safe_remove_file_under_storage(disk_path: str) -> None:
    root = os.path.realpath(settings.photo_storage_dir)
    try:
        rp = os.path.realpath(disk_path)
    except OSError:
        return
    sep = os.sep
    if not (rp == root or rp.startswith(root + sep)):
        return
    if os.path.isfile(rp):
        try:
            os.remove(rp)
        except OSError:
            pass


def _safe_rmtree_session(key: str) -> None:
    root = os.path.realpath(settings.photo_storage_dir)
    try:
        d = os.path.realpath(_session_dir(key))
    except OSError:
        return
    sep = os.sep
    if not (d == root or d.startswith(root + sep)):
        return
    if os.path.isdir(d):
        try:
            shutil.rmtree(d)
        except OSError:
            pass


@router.post("/register", response_model=RegisterOut)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    exists = db.query(User).filter(User.account == body.account.strip()).first()
    if exists:
        raise HTTPException(status_code=400, detail="账号已存在")

    role = "user"
    if body.admin_invite_code and body.admin_invite_code.strip() == settings.admin_invite_code:
        role = "admin"
    elif body.admin_invite_code:
        raise HTTPException(status_code=400, detail="管理员邀请码错误")

    u = User(
        account=body.account.strip(),
        password_hash=hash_password(body.password),
        role=role,
        nickname=body.nickname.strip() or body.account.strip(),
        avatar="",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    user_public = UserPublic(id=u.id, account=u.account, role=u.role, nickname=u.nickname, avatar=u.avatar)
    token = create_access_token({"sub": u.id, "role": u.role})
    return RegisterOut(access_token=token, user=user_public)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.account == body.account.strip()).first()
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    token = create_access_token({"sub": u.id, "role": u.role})
    return TokenOut(access_token=token)


@router.get("/me", response_model=UserPublic)
def me(user: User = Depends(require_user)):
    return UserPublic(id=user.id, account=user.account, role=user.role, nickname=user.nickname, avatar=user.avatar)


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    body: DeleteAccountIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="密码错误")

    uid = user.id
    owned_sessions = db.query(CaptureSession).filter(CaptureSession.owner_user_id == uid).all()
    session_ids = [s.id for s in owned_sessions]

    photo_filter = Photo.owner_user_id == uid
    if session_ids:
        photo_filter = or_(Photo.owner_user_id == uid, Photo.session_id.in_(session_ids))

    photos = db.query(Photo).filter(photo_filter).all()
    seen_paths: Set[str] = set()
    for ph in photos:
        dp = (ph.disk_path or "").strip()
        if dp and dp not in seen_paths:
            seen_paths.add(dp)
            _safe_remove_file_under_storage(dp)

    db.query(Photo).filter(photo_filter).delete(synchronize_session=False)

    for sess in owned_sessions:
        k = _storage_session_key(sess)
        _safe_rmtree_session(k)
        if k != sess.id:
            _safe_rmtree_session(sess.id)

    db.query(CaptureSession).filter(CaptureSession.owner_user_id == uid).delete(synchronize_session=False)

    db.query(RobotConnectHistory).filter(RobotConnectHistory.user_id == uid).delete(synchronize_session=False)
    db.query(PaymentRecord).filter(PaymentRecord.user_id == uid).delete(synchronize_session=False)
    db.query(PaymentDailySeq).filter(PaymentDailySeq.user_id == uid).delete(synchronize_session=False)
    db.query(RecommendLike).filter(RecommendLike.user_id == uid).delete(synchronize_session=False)
    db.query(RecommendSpot).filter(RecommendSpot.created_by == uid).update(
        {"created_by": None},
        synchronize_session=False,
    )

    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
