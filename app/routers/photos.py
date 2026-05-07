from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_user
from app.models import Photo, User
from app.schemas import PhotoOut

router = APIRouter(prefix="/api/photos", tags=["photos"])


@router.get("/mine", response_model=List[PhotoOut])
def my_photos(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    limit: int = 200,
):
    rows = (
        db.query(Photo)
        .filter(Photo.owner_user_id == user.id)
        .order_by(Photo.capture_time.desc(), Photo.file_name.asc(), Photo.id.asc())
        .limit(min(limit, 500))
        .all()
    )
    return [
        PhotoOut(
            id=p.id,
            session_id=p.session_id,
            owner_user_id=p.owner_user_id,
            file_name=p.file_name,
            url=p.public_path,
            robot_id=p.robot_id or "",
            capture_time=p.capture_time,
            file_size=p.file_size,
        )
        for p in rows
    ]
