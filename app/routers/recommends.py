import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_optional_user, require_admin, require_user
from app.models import RecommendLike, RecommendSpot, User
from app.schemas import RecommendCreateIn, RecommendOut, RecommendUpdateIn

router = APIRouter(prefix="/api/recommends", tags=["recommends"])


def _detail_list(spot: RecommendSpot) -> List[str]:
    try:
        return json.loads(spot.detail_images_json or "[]")
    except json.JSONDecodeError:
        return []


def _to_out(db: Session, spot: RecommendSpot, user: Optional[User]) -> RecommendOut:
    likes_count = (
        db.query(func.count(RecommendLike.id)).filter(RecommendLike.recommend_id == spot.id).scalar()
        or 0
    )
    liked_by_me = False
    if user:
        liked_by_me = (
            db.query(RecommendLike.id).filter_by(user_id=user.id, recommend_id=spot.id).first()
            is not None
        )
    return RecommendOut(
        id=spot.id,
        name=spot.name,
        description=spot.description or "",
        tips=spot.tips or "",
        cover_image_url=spot.cover_image_url or "",
        detail_images=_detail_list(spot),
        likes_count=int(likes_count),
        liked_by_me=liked_by_me,
    )


@router.get("", response_model=List[RecommendOut])
def list_spots(db: Session = Depends(get_db), viewer: Optional[User] = Depends(get_optional_user)):
    spots = db.query(RecommendSpot).order_by(RecommendSpot.created_at.desc()).all()
    return [_to_out(db, s, viewer) for s in spots]


@router.get("/{spot_id}", response_model=RecommendOut)
def get_spot(
    spot_id: str,
    db: Session = Depends(get_db),
    viewer: Optional[User] = Depends(get_optional_user),
):
    s = db.query(RecommendSpot).filter(RecommendSpot.id == spot_id).first()
    if not s:
        raise HTTPException(404, "景点不存在")
    return _to_out(db, s, viewer)


@router.post("", response_model=RecommendOut)
def create_spot(
    body: RecommendCreateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    spot = RecommendSpot(
        name=body.name,
        description=body.description,
        tips=body.tips,
        cover_image_url=body.cover_image_url,
        detail_images_json=json.dumps(body.detail_images or [], ensure_ascii=False),
        created_by=admin.id,
    )
    db.add(spot)
    db.commit()
    db.refresh(spot)
    return _to_out(db, spot, admin)


@router.put("/{spot_id}", response_model=RecommendOut)
def update_spot(
    spot_id: str,
    body: RecommendUpdateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    s = db.query(RecommendSpot).filter(RecommendSpot.id == spot_id).first()
    if not s:
        raise HTTPException(404, "景点不存在")
    if body.name is not None:
        s.name = body.name
    if body.description is not None:
        s.description = body.description
    if body.tips is not None:
        s.tips = body.tips
    if body.cover_image_url is not None:
        s.cover_image_url = body.cover_image_url
    if body.detail_images is not None:
        s.detail_images_json = json.dumps(body.detail_images, ensure_ascii=False)
    db.commit()
    db.refresh(s)
    return _to_out(db, s, admin)


@router.delete("/{spot_id}")
def delete_spot(spot_id: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    s = db.query(RecommendSpot).filter(RecommendSpot.id == spot_id).first()
    if not s:
        raise HTTPException(404, "景点不存在")
    db.query(RecommendLike).filter(RecommendLike.recommend_id == spot_id).delete()
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.post("/{spot_id}/like")
def like_spot(spot_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    s = db.query(RecommendSpot).filter(RecommendSpot.id == spot_id).first()
    if not s:
        raise HTTPException(404, "景点不存在")
    exists = db.query(RecommendLike).filter_by(user_id=user.id, recommend_id=spot_id).first()
    if exists:
        return {"ok": True, "liked": True}
    db.add(RecommendLike(user_id=user.id, recommend_id=spot_id))
    db.commit()
    return {"ok": True, "liked": True}


@router.delete("/{spot_id}/like")
def unlike_spot(spot_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    db.query(RecommendLike).filter_by(user_id=user.id, recommend_id=spot_id).delete()
    db.commit()
    return {"ok": True, "liked": False}
