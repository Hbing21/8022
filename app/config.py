import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    app_name: str
    secret_key: str
    algorithm: str
    access_token_expire_minutes: int
    admin_invite_code: str
    robot_origin: str
    photo_storage_dir: str
    database_url: str
    guest_session_hours: int


@lru_cache(maxsize=None)
def get_settings() -> Settings:
    return Settings(
        app_name="RobotUserBackend",
        secret_key=os.getenv("JWT_SECRET_KEY", "change-me-in-production-use-long-random-string"),
        algorithm="HS256",
        access_token_expire_minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 7))),
        admin_invite_code=os.getenv("ADMIN_INVITE_CODE", "robot2026"),
        robot_origin=os.getenv("ROBOT_ORIGIN", "http://192.168.0.73:8021").rstrip("/"),
        photo_storage_dir=os.getenv("PHOTO_STORAGE_DIR", "/home/lab/robot_photos"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./robot_user.db"),
        guest_session_hours=int(os.getenv("GUEST_SESSION_HOURS", "24")),
    )
