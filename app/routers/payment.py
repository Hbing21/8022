from datetime import datetime, timedelta, timezone
import os
import re
import time
from typing import List, Optional, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_user
from app.models import PaymentDailySeq, PaymentRecord, Photo, User
from app.schemas import PaymentCreateIn, PaymentOut, PaymentStatusOut
from app.time_display import format_capture_for_photo_id

router = APIRouter(prefix="/api/payment", tags=["payment"])

_re_photo_n = re.compile(r"photo_(\d+)", re.IGNORECASE)
_re_human_photo_id = re.compile(r"^\d{8}_\d{2}_photo\d+$")


def _display_tz() -> timezone:
    name = (os.getenv("PAYMENT_DISPLAY_TZ") or "Asia/Shanghai").strip()
    low = name.lower()
    if low in ("utc", "z"):
        return timezone.utc
    # Python 3.8 兼容：默认使用 UTC+8（Asia/Shanghai）
    if low in ("asia/shanghai", "prc", "cst", "utc+8", "gmt+8", "+08:00"):
        return timezone(timedelta(hours=8))
    return timezone(timedelta(hours=8))


def _as_local_time(dt: datetime) -> datetime:
    """
    统一转为 PAYMENT_DISPLAY_TZ（默认 Asia/Shanghai）。

    约定：
    - PaymentRecord.pay_time 历史上主要为 UTC naive（datetime.utcnow 写入）
    - 因此 naive datetime 必须先按 UTC 解释，再换算到展示时区
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_display_tz())


def _photo_display_id_from_photo(photo: Optional[Photo], fallback: str) -> str:
    """
    订单详情里展示的“照片ID”：YYYYMMDD_HH_photoN（仅到小时）。
    前缀日期时间为拍摄会话时间（Photo.capture_time，来自机器人会话目录解析），
    与订单号中的支付时刻无关。
    N 尽量从 file_name 提取（photo_9.jpg -> 9）。
    """
    if photo is None:
        return fallback
    ct = getattr(photo, "capture_time", None)
    ts = format_capture_for_photo_id(ct) if ct else ""
    name = (getattr(photo, "file_name", "") or "").strip()
    stem = os.path.splitext(name)[0] if name else ""
    n = ""
    m = _re_photo_n.search(stem)
    if m:
        n = m.group(1)
    if ts and n:
        return f"{ts}_photo{n}"
    if ts and stem:
        # 兜底：用不带后缀的文件名
        return f"{ts}_{stem}"
    return fallback


def _resolved_photo_display_id(record: PaymentRecord, photo_map: Dict[str, Photo]) -> str:
    """
    历史展示优先使用 Photo.capture_time + file_name 生成标准格式：
    YYYYMMDD_HH_photoN
    """
    ph = photo_map.get(record.photo_id)
    if ph is not None:
        return _photo_display_id_from_photo(ph, fallback=(record.photo_display_id or "").strip() or record.photo_id)
    old = (record.photo_display_id or "").strip()
    return old if old else record.photo_id


def _next_order_id(db: Session, user_id: str) -> str:
    """订单号前缀为服务端支付时刻（本地墙钟），与照片展示 ID 的拍摄会话时间无关。"""
    now = datetime.now()
    yyyymmdd = now.strftime("%Y%m%d")
    hhmmss = now.strftime("%H%M%S")

    seq_row = (
        db.query(PaymentDailySeq)
        .filter(PaymentDailySeq.user_id == user_id, PaymentDailySeq.yyyymmdd == yyyymmdd)
        .first()
    )
    if seq_row is None:
        seq_row = PaymentDailySeq(user_id=user_id, yyyymmdd=yyyymmdd, last_seq=1)
        db.add(seq_row)
        seq = 1
    else:
        seq = int(seq_row.last_seq or 0) + 1
        seq_row.last_seq = seq
    return f"P{yyyymmdd}_{hhmmss}_{seq:04d}"


@router.post("/create", response_model=PaymentOut)
def create_payment(
    body: PaymentCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    photo_id = (body.photo_id or "").strip()
    if not photo_id:
        raise HTTPException(status_code=400, detail="photo_id 不能为空")
    photo = (
        db.query(Photo)
        .filter(Photo.id == photo_id, Photo.owner_user_id == user.id)
        .first()
    )
    if photo is None:
        raise HTTPException(status_code=404, detail="照片不存在或无权支付")
    # 统一由服务端生成展示用照片ID（订单详情/历史支付更可读）
    photo_display_id = _photo_display_id_from_photo(
        photo,
        fallback=(body.photo_display_id or "").strip() or (photo.file_name or "").strip() or photo_id,
    )
    # 使用 UTC aware，避免后续链路对 naive 时区语义产生歧义
    pay_time = datetime.now(timezone.utc)

    # 幂等：同一用户同一照片已支付成功时，直接返回已有订单，避免重复支付
    already_paid = (
        db.query(PaymentRecord)
        .filter(
            PaymentRecord.user_id == user.id,
            PaymentRecord.photo_id == photo_id,
            PaymentRecord.status == "支付成功",
        )
        .order_by(PaymentRecord.pay_time.desc())
        .first()
    )
    if already_paid:
        shown_display = already_paid.photo_display_id or ""
        if not shown_display or not _re_human_photo_id.match(shown_display):
            shown_display = photo_display_id
        return PaymentOut(
            id=already_paid.id,
            order_id=already_paid.order_id,
            photo_id=already_paid.photo_id,
            photo_display_id=shown_display,
            robot_id=already_paid.robot_id,
            amount=float(already_paid.amount or 0.0),
            pay_time=_as_local_time(already_paid.pay_time),
            status=already_paid.status,
        )

    custom_order_id = (body.order_id or "").strip()

    # 轻量重试：处理并发/锁冲突（SQLite database is locked 等）
    attempts = 4
    for idx in range(attempts):
        try:
            order_id = custom_order_id or _next_order_id(db, user.id)

            # 幂等：同用户同订单号重复提交时，直接返回已有记录
            exists = (
                db.query(PaymentRecord)
                .filter(PaymentRecord.user_id == user.id, PaymentRecord.order_id == order_id)
                .first()
            )
            if exists:
                shown_display = exists.photo_display_id or ""
                if not shown_display or not _re_human_photo_id.match(shown_display):
                    shown_display = photo_display_id
                return PaymentOut(
                    id=exists.id,
                    order_id=exists.order_id,
                    photo_id=exists.photo_id,
                    photo_display_id=shown_display,
                    robot_id=exists.robot_id,
                    amount=float(exists.amount or 0.0),
                    pay_time=_as_local_time(exists.pay_time),
                    status=exists.status,
                )

            create_kwargs = {
                "user_id": user.id,
                "order_id": order_id,
                "photo_id": photo_id,
                "robot_id": (body.robot_id or "").strip(),
                "amount": float(body.amount or 0.0),
                "status": "支付成功",
                "pay_time": pay_time,
            }
            # 兼容旧版本模型：若 PaymentRecord 没有 photo_display_id 字段，则不写入（避免 500）。
            if hasattr(PaymentRecord, "photo_display_id"):
                create_kwargs["photo_display_id"] = photo_display_id

            r = PaymentRecord(**create_kwargs)
            db.add(r)
            db.commit()
            db.refresh(r)
            return PaymentOut(
                id=r.id,
                order_id=r.order_id,
                photo_id=r.photo_id,
                photo_display_id=getattr(r, "photo_display_id", "") or "",
                robot_id=r.robot_id,
                amount=float(r.amount or 0.0),
                pay_time=_as_local_time(r.pay_time),
                status=r.status,
            )
        except IntegrityError:
            db.rollback()
            if idx >= attempts - 1:
                raise HTTPException(status_code=409, detail="订单创建冲突，请重试")
            time.sleep(0.05 * (idx + 1))
        except OperationalError:
            db.rollback()
            if idx >= attempts - 1:
                raise HTTPException(status_code=503, detail="数据库繁忙，请稍后重试")
            time.sleep(0.1 * (idx + 1))

    raise HTTPException(status_code=500, detail="订单创建失败")


@router.get("/history", response_model=List[PaymentOut])
def list_history(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    limit: int = 50,
    photo_id: Optional[str] = None,
):
    q = db.query(PaymentRecord).filter(PaymentRecord.user_id == user.id)
    if photo_id:
        q = q.filter(PaymentRecord.photo_id == photo_id)
    rows = q.order_by(PaymentRecord.pay_time.desc()).limit(min(limit, 200)).all()
    # 批量补全“人读照片ID”：旧记录可能只存了 photo_9.jpg
    photo_ids_need = [
        r.photo_id
        for r in rows
        if not (r.photo_display_id or "").strip() or not _re_human_photo_id.match((r.photo_display_id or "").strip())
    ]
    photo_map = {}
    if photo_ids_need:
        ph_rows = db.query(Photo).filter(Photo.id.in_(photo_ids_need)).all()
        photo_map = {p.id: p for p in ph_rows}
    return [
        PaymentOut(
            id=r.id,
            order_id=r.order_id,
            photo_id=r.photo_id,
            photo_display_id=_resolved_photo_display_id(r, photo_map),
            robot_id=r.robot_id,
            amount=float(r.amount or 0.0),
            pay_time=_as_local_time(r.pay_time),
            status=r.status,
        )
        for r in rows
    ]


@router.get("/status/{order_id}", response_model=PaymentStatusOut)
def get_status(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    oid = (order_id or "").strip()
    if not oid:
        raise HTTPException(status_code=400, detail="order_id 不能为空")
    r = (
        db.query(PaymentRecord)
        .filter(PaymentRecord.user_id == user.id, PaymentRecord.order_id == oid)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="订单不存在")
    return PaymentStatusOut(order_id=r.order_id, status=r.status)

