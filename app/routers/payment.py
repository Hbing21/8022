from datetime import datetime
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_user
from app.models import PaymentDailySeq, PaymentRecord, Photo, User
from app.schemas import PaymentCreateIn, PaymentOut, PaymentStatusOut

router = APIRouter(prefix="/api/payment", tags=["payment"])


def _next_order_id(db: Session, user_id: str) -> str:
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
    photo_display_id = (body.photo_display_id or "").strip() or (photo.file_name or "").strip() or photo_id

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
        return PaymentOut(
            id=already_paid.id,
            order_id=already_paid.order_id,
            photo_id=already_paid.photo_id,
            photo_display_id=already_paid.photo_display_id or "",
            robot_id=already_paid.robot_id,
            amount=float(already_paid.amount or 0.0),
            pay_time=already_paid.pay_time,
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
                return PaymentOut(
                    id=exists.id,
                    order_id=exists.order_id,
                    photo_id=exists.photo_id,
                    photo_display_id=exists.photo_display_id or "",
                    robot_id=exists.robot_id,
                    amount=float(exists.amount or 0.0),
                    pay_time=exists.pay_time,
                    status=exists.status,
                )

            create_kwargs = {
                "user_id": user.id,
                "order_id": order_id,
                "photo_id": photo_id,
                "robot_id": (body.robot_id or "").strip(),
                "amount": float(body.amount or 0.0),
                "status": "支付成功",
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
                pay_time=r.pay_time,
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
    return [
        PaymentOut(
            id=r.id,
            order_id=r.order_id,
            photo_id=r.photo_id,
            photo_display_id=r.photo_display_id or "",
            robot_id=r.robot_id,
            amount=float(r.amount or 0.0),
            pay_time=r.pay_time,
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

