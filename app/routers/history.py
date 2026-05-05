from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_user
from app.models import RobotConnectHistory, User
from app.schemas import ConnectHistoryIn, ConnectHistoryOut

router = APIRouter(prefix="/api/history", tags=["history"])


@router.post("/robot-connect", response_model=ConnectHistoryOut)
def add_connect(
    body: ConnectHistoryIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    h = RobotConnectHistory(
        user_id=user.id,
        robot_id=body.robot_id,
        is_success=body.is_success,
        status=body.status[:250] if body.status else "",
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return ConnectHistoryOut(
        id=h.id,
        robot_id=h.robot_id,
        connect_time=h.connect_time,
        is_success=h.is_success,
        status=h.status,
    )


@router.get("/robot-connect", response_model=List[ConnectHistoryOut])
def list_connect(db: Session = Depends(get_db), user: User = Depends(require_user), limit: int = 50):
    rows = (
        db.query(RobotConnectHistory)
        .filter(RobotConnectHistory.user_id == user.id)
        .order_by(RobotConnectHistory.connect_time.desc())
        .limit(min(limit, 200))
        .all()
    )
    return [
        ConnectHistoryOut(
            id=r.id,
            robot_id=r.robot_id,
            connect_time=r.connect_time,
            is_success=r.is_success,
            status=r.status,
        )
        for r in rows
    ]
