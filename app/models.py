import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_uuid)
    account = Column(String(128), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(16), nullable=False, default="user")
    nickname = Column(String(128), default="")
    avatar = Column(String(512), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class CaptureSession(Base):
    __tablename__ = "capture_sessions"

    id = Column(String(36), primary_key=True, default=_uuid)
    robot_id = Column(String(128), nullable=False, default="")
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    guest_token = Column(String(128), nullable=True, unique=True, index=True)
    status = Column(String(32), default="pending")
    robot_session_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)


class Photo(Base):
    __tablename__ = "photos"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(String(36), ForeignKey("capture_sessions.id"), nullable=False, index=True)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    robot_id = Column(String(128), default="")
    file_name = Column(String(512), nullable=False)
    disk_path = Column(String(1024), nullable=False)
    public_path = Column(String(1024), nullable=False)
    capture_time = Column(DateTime, default=datetime.utcnow)
    file_size = Column(Float, nullable=True)


class RobotConnectHistory(Base):
    __tablename__ = "robot_connect_history"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    robot_id = Column(String(128), nullable=False)
    connect_time = Column(DateTime, default=datetime.utcnow)
    is_success = Column(Boolean, default=True)
    status = Column(String(256), default="")


class RecommendSpot(Base):
    __tablename__ = "recommend_spots"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(256), nullable=False)
    description = Column(Text, default="")
    tips = Column(Text, default="")
    cover_image_url = Column(String(1024), default="")
    detail_images_json = Column(Text, default="[]")  # JSON array of URLs
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RecommendLike(Base):
    __tablename__ = "recommend_likes"
    __table_args__ = (UniqueConstraint("user_id", "recommend_id", name="uq_user_recommend_like"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    recommend_id = Column(String(36), ForeignKey("recommend_spots.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PaymentRecord(Base):
    __tablename__ = "payment_records"
    __table_args__ = (UniqueConstraint("user_id", "order_id", name="uq_user_order"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    order_id = Column(String(128), nullable=False, index=True)
    photo_id = Column(String(36), ForeignKey("photos.id"), nullable=False, index=True)
    photo_display_id = Column(String(256), nullable=False, default="")
    robot_id = Column(String(128), nullable=False, default="")
    amount = Column(Float, nullable=False, default=0.0)
    status = Column(String(64), nullable=False, default="支付成功")
    pay_time = Column(DateTime, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PaymentDailySeq(Base):
    __tablename__ = "payment_daily_seq"
    __table_args__ = (UniqueConstraint("user_id", "yyyymmdd", name="uq_payment_daily_seq"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    yyyymmdd = Column(String(8), nullable=False, index=True)
    last_seq = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
