from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config
from ..clock import now
from ..database import get_db
from ..models import User
from ..security import (check_password_strength, current_user, hash_password, normalise_phone,
                        verify_password)
from ..serialize import user_dict
from ..services import audit, aware

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _needs_setup(db: Session) -> bool:
    return db.scalar(select(func.count(User.id))) == 0


@router.get("/state")
def state(request: Request, db: Session = Depends(get_db)):
    """Tells the page whether to show first-run setup, the login form, or the app."""
    if _needs_setup(db):
        return {"needs_setup": True, "user": None}
    try:
        user = current_user(request, db)
    except HTTPException:
        return {"needs_setup": False, "user": None}
    return {"needs_setup": False, "user": user_dict(user), "categories": config.CATEGORIES}


@router.post("/setup")
def first_run_setup(body: dict, request: Request, db: Session = Depends(get_db)):
    """Creates the first administrator. Only works while there are no users at all."""
    if not _needs_setup(db):
        raise HTTPException(409, "Setup has already been done. Please sign in.")
    name = (body.get("full_name") or "").strip()
    if not name:
        raise HTTPException(400, "Enter your full name.")
    pw = body.get("password") or ""
    check_password_strength(pw)
    u = User(phone=normalise_phone(body.get("phone")), full_name=name, role="admin",
             password_hash=hash_password(pw))
    db.add(u)
    db.flush()
    audit(db, u, "setup", f"Administrator {name} created")
    db.commit()
    request.session.clear()
    request.session["uid"] = u.id
    return {"user": user_dict(u)}


@router.post("/login")
def login(body: dict, request: Request, db: Session = Depends(get_db)):
    phone = normalise_phone(body.get("phone"))
    pw = body.get("password") or ""
    u = db.scalar(select(User).where(User.phone == phone))
    bad = HTTPException(401, "Wrong phone number or password.")
    if not u or not u.is_active:
        raise bad
    locked = aware(u.locked_until)
    if locked and locked > now():
        mins = max(1, int((locked - now()).total_seconds() // 60) + 1)
        raise HTTPException(429, f"Too many wrong attempts. Try again in {mins} minute(s).")
    if not verify_password(pw, u.password_hash):
        u.failed_logins = (u.failed_logins or 0) + 1
        if u.failed_logins >= config.LOGIN_MAX_FAILS:
            u.locked_until = now() + timedelta(minutes=config.LOGIN_LOCK_MIN)
            u.failed_logins = 0
            audit(db, u, "login_locked", f"Locked for {config.LOGIN_LOCK_MIN} min after repeated failures")
        db.commit()
        raise bad
    u.failed_logins = 0
    u.locked_until = None
    audit(db, u, "login")
    db.commit()
    request.session.clear()
    request.session["uid"] = u.id
    return {"user": user_dict(u)}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.post("/password")
def change_password(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not verify_password(body.get("current_password") or "", user.password_hash):
        raise HTTPException(400, "Your current password is not correct.")
    check_password_strength(body.get("new_password") or "")
    user.password_hash = hash_password(body["new_password"])
    audit(db, user, "password_changed")
    db.commit()
    return {"ok": True}
