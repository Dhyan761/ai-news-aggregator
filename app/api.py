import os
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, or_

load_dotenv()

from app.daily_runner import run_daily_pipeline
from app.database.connection import engine, get_session
from app.database.models import Base, Digest

STATIC_DIR = Path(__file__).parent / "static"

@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="AI News Aggregator", lifespan=lifespan)

_pipeline_lock = threading.Lock()
_last_run: dict = {"running": False, "result": None}


def _serialize(d: Digest) -> dict:
    return {
        "id": d.id,
        "source": d.article_type,
        "title": d.title,
        "summary": d.summary,
        "url": d.url,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "sent_at": d.sent_at.isoformat() if d.sent_at else None,
    }


@app.get("/api/digests")
def list_digests(
    source: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    session = get_session()
    try:
        query = session.query(Digest)
        if source:
            query = query.filter(Digest.article_type == source)
        if q:
            pattern = f"%{q}%"
            query = query.filter(
                or_(Digest.title.ilike(pattern), Digest.summary.ilike(pattern))
            )
        total = query.count()
        rows = (
            query.order_by(Digest.created_at.desc()).offset(offset).limit(limit).all()
        )
        return {"total": total, "items": [_serialize(d) for d in rows]}
    finally:
        session.close()


@app.get("/api/stats")
def stats():
    session = get_session()
    try:
        counts = dict(
            session.query(Digest.article_type, func.count(Digest.id))
            .group_by(Digest.article_type)
            .all()
        )
        latest = session.query(func.max(Digest.created_at)).scalar()
        return {
            "total": sum(counts.values()),
            "by_source": counts,
            "latest": latest.isoformat() if latest else None,
            "pipeline_running": _last_run["running"],
        }
    finally:
        session.close()


def _run_pipeline_in_background():
    try:
        _last_run["result"] = run_daily_pipeline(hours=24, top_n=10)
    finally:
        _last_run["running"] = False
        _pipeline_lock.release()


@app.post("/api/run-pipeline", status_code=202)
def trigger_pipeline(x_admin_token: Optional[str] = Header(None)):
    expected = os.getenv("ADMIN_TOKEN")
    if not expected or not x_admin_token or not secrets.compare_digest(
        x_admin_token, expected
    ):
        raise HTTPException(status_code=401, detail="Invalid admin token")
    if not _pipeline_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Pipeline already running")
    _last_run["running"] = True
    threading.Thread(target=_run_pipeline_in_background, daemon=True).start()
    return {"status": "started"}


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
