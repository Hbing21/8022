import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, SessionLocal, engine
import app.models  # noqa: F401  # 确保所有表模型被注册到 Base.metadata
from app.routers import auth, capture, files, history, payment, photos, recommends
from app.services.cleanup import cleanup_expired_guest_sessions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    asyncio.create_task(_cleanup_loop())

    yield


async def _cleanup_loop():
    while True:
        await asyncio.sleep(3600)
        db = SessionLocal()
        try:
            n = cleanup_expired_guest_sessions(db)
            if n:
                logger.info("cleanup: removed %d expired guest session(s)", n)
        except Exception:
            logger.exception("cleanup loop error")
        finally:
            db.close()


app = FastAPI(title="Robot User Backend", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(recommends.router)
app.include_router(capture.router)
app.include_router(history.router)
app.include_router(payment.router)
app.include_router(photos.router)
app.include_router(files.router)


@app.get("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8022, reload=False)
