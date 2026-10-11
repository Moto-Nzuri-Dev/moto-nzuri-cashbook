"""Passwords, sessions and permission checks."""
import hashlib
import hmac
import secrets
import time

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from . import config
from .database import get_db
from .models import Float, User

_ITER = 390_000


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), _ITER)
    return f"pbkdf2_sha256${_ITER}${salt}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except (ValueError, AttributeError):
        return False


def check_password_strength(pw: str) -> None:
    if len(pw or "") < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")


def normalise_phone(raw: str) -> str:
    """0712 345 678, +254712345678 and 254712345678 all become 0712345678."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if digits.startswith("254") and len(digits) == 12:
        digits = "0" + digits[3:]
    if len(digits) == 9 and digits[0] in "17":
        digits = "0" + digits
    if not (len(digits) == 10 and digits.startswith("0")):
        raise HTTPException(400, "Enter a valid Kenyan phone number, e.g. 0712345678.")
    return digits


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = request.session.get("uid")
    if not uid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in.")
    t = time.time()
    seen = request.session.get("seen", t)
    if config.IDLE_TIMEOUT_MIN and t - seen > config.IDLE_TIMEOUT_MIN * 60:
        request.session.clear()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Signed out after inactivity. Please sign in again.")
    request.session["seen"] = t
    user = db.get(User, uid)
    if not user or not user.is_active:
        request.session.clear()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in.")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Only the administrator can do this.")
    return user


def sees_all(user: User) -> bool:
    """Admin and boss see every manager; managers see only their own records."""
    return user.role in ("admin", "boss")


def can_hold_floats(user: User) -> bool:
    return user.role in ("admin", "manager")


def guard_view_float(user: User, f: Float | None) -> Float:
    if f is None or (not sees_all(user) and f.manager_id != user.id):
        raise HTTPException(404, "Float not found.")
    return f


def guard_edit_float(user: User, f: Float | None) -> Float:
    """Only the float's own manager may change it, and only while it is OPEN or QUERIED."""
    f = guard_view_float(user, f)
    if f.manager_id != user.id:
        raise HTTPException(403, "Only the manager who holds this float can change it.")
    if f.status in ("SUBMITTED", "APPROVED"):
        raise HTTPException(409, "This float is locked (submitted or approved). No changes allowed.")
    return f
