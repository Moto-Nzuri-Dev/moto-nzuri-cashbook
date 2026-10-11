"""People, settings and the audit trail — administrator only (settings are readable by all)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..database import get_db
from ..models import AuditLog, ROLES, User
from ..security import (check_password_strength, current_user, hash_password, normalise_phone,
                        require_admin)
from ..serialize import user_dict
from ..services import audit, aware, kes, proof_threshold, set_setting, to_cents

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/users")
def list_users(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if user.role == "manager":
        return [user_dict(user)]
    return [user_dict(u) for u in db.scalars(select(User).order_by(User.full_name))]


@router.post("/users")
def create_user(body: dict, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    role = body.get("role", "manager")
    if role not in ROLES:
        raise HTTPException(400, "Role must be admin, manager or boss.")
    name = (body.get("full_name") or "").strip()
    if not name:
        raise HTTPException(400, "Enter the person's full name.")
    phone = normalise_phone(body.get("phone"))
    if db.scalar(select(User).where(User.phone == phone)):
        raise HTTPException(409, "Someone already uses that phone number.")
    pw = body.get("password") or ""
    check_password_strength(pw)
    u = User(phone=phone, full_name=name, role=role, password_hash=hash_password(pw))
    db.add(u)
    db.flush()
    audit(db, admin, "user_created", f"{name} ({role}, {phone})")
    db.commit()
    return user_dict(u)


@router.patch("/users/{uid}")
def update_user(uid: int, body: dict, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "User not found.")
    changes = []
    if "full_name" in body and body["full_name"].strip():
        u.full_name = body["full_name"].strip(); changes.append("name")
    if "role" in body:
        if body["role"] not in ROLES:
            raise HTTPException(400, "Role must be admin, manager or boss.")
        if u.id == admin.id and body["role"] != "admin":
            raise HTTPException(400, "You can't remove your own administrator role.")
        u.role = body["role"]; changes.append(f"role={u.role}")
    if "is_active" in body:
        if u.id == admin.id and not body["is_active"]:
            raise HTTPException(400, "You can't deactivate yourself.")
        u.is_active = bool(body["is_active"]); changes.append(f"active={u.is_active}")
    if body.get("password"):
        check_password_strength(body["password"])
        u.password_hash = hash_password(body["password"])
        u.failed_logins, u.locked_until = 0, None
        changes.append("password reset")
    audit(db, admin, "user_updated", f"{u.full_name}: {', '.join(changes) or 'no change'}")
    db.commit()
    return user_dict(u)


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"proof_threshold": kes(proof_threshold(db)), "categories": config.CATEGORIES}


@router.put("/settings")
def put_settings(body: dict, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if "proof_threshold" in body:
        cents = to_cents(body["proof_threshold"], "Proof threshold", allow_zero=True)
        set_setting(db, "proof_threshold_cents", str(cents))
        audit(db, admin, "settings", f"Proof required from KES {kes(cents):,.0f}")
    db.commit()
    return get_settings(db, admin)


@router.get("/audit")
def audit_log(limit: int = 200, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    rows = db.execute(
        select(AuditLog, User.full_name).outerjoin(User, AuditLog.user_id == User.id)
        .order_by(AuditLog.id.desc()).limit(min(max(limit, 1), 1000))).all()
    return [{"at": aware(a.at).isoformat(), "who": name or "-", "action": a.action, "detail": a.detail}
            for a, name in rows]
