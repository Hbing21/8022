from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account: str
    role: str
    nickname: str
    avatar: str


class RegisterIn(BaseModel):
    account: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    nickname: str = ""
    admin_invite_code: Optional[str] = None


class LoginIn(BaseModel):
    account: str
    password: str


class RecommendOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    tips: str
    cover_image_url: str
    detail_images: List[str]
    likes_count: int = 0
    liked_by_me: bool = False


class RecommendCreateIn(BaseModel):
    name: str
    description: str = ""
    tips: str = ""
    cover_image_url: str = ""
    detail_images: List[str] = []


class RecommendUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tips: Optional[str] = None
    cover_image_url: Optional[str] = None
    detail_images: Optional[List[str]] = None


class CaptureStartIn(BaseModel):
    robot_id: str = ""


class CaptureStartOut(BaseModel):
    session_id: str
    guest_token: Optional[str] = None
    expires_at: Optional[datetime] = None


class PhotoOut(BaseModel):
    id: str
    session_id: str
    owner_user_id: Optional[str]
    file_name: str
    url: str
    capture_time: datetime


class ClaimIn(BaseModel):
    guest_token: str


class ConnectHistoryIn(BaseModel):
    robot_id: str
    is_success: bool = True
    status: str = ""


class ConnectHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    robot_id: str
    connect_time: datetime
    is_success: bool
    status: str
