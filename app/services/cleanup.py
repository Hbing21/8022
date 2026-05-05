import os
import shutil
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CaptureSession, Photo

settings = get_settings()


def cleanup_expired_guest_sessions(db: Session) -> int:
    now = datetime.utcnow()
    stale = (
        db.query(CaptureSession)
        .filter(
            CaptureSession.owner_user_id.is_(None),
            CaptureSession.expires_at.isnot(None),
            CaptureSession.expires_at < now,
        )
        .all()
    )
    n = 0
    for s in stale:
        d = os.path.join(settings.photo_storage_dir, "sessions", s.id)
        shutil.rmtree(d, ignore_errors=True)
        db.query(Photo).filter(Photo.session_id == s.id).delete(synchronize_session=False)
        db.delete(s)
        n += 1
    if n:
        db.commit()
    return n
