from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_optional_user, require_user
from app.models import User
from app.schemas import LoginIn, RegisterIn, TokenOut, UserPublic
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


@router.post("/register", response_model=UserPublic)
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
    return UserPublic(id=u.id, account=u.account, role=u.role, nickname=u.nickname, avatar=u.avatar)


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
