"""Moto Nzuri Cashbook — Cash Book & Float Management System.

Run locally:   python run.py            (opens on http://localhost:8000)
Production:    uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import config
from .database import Base, SessionLocal, engine
from .routers import admin, auth, dashboard, field_reports, floats

log = logging.getLogger("cashbook")
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    if config.SECRET_KEY == "dev-only-change-me":
        log.warning("SECRET_KEY is not set — fine for local testing, NOT for the live site.")
    yield


app = FastAPI(title="Moto Nzuri Cashbook", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def protect(request: Request, call_next):
    # Simple CSRF guard: every change to data must come from our own page, which sends this header.
    # Browsers will not let another website add it.
    if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get("x-cashbook") != "1":
            return JSONResponse({"detail": "Request blocked."}, status_code=403)
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY, session_cookie="cashbook_session",
                   max_age=60 * 60 * 24 * 14, same_site="lax", https_only=config.COOKIE_SECURE)

for r in (auth, admin, floats, dashboard, field_reports):
    app.include_router(r.router)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse({"detail": "Some of the information sent was not valid. Please check and try again."},
                        status_code=422)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Something went wrong on the server. Your data is safe — please try again."},
                        status_code=500)


@app.get("/api/health")
def health():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"ok": True, "database": "postgres" if "postgresql" in config.DATABASE_URL else "sqlite"}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found."}, status_code=404)
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
