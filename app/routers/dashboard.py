from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Float, User
from ..security import current_user, sees_all
from ..services import float_totals, kes, proof_threshold

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)):
    th = proof_threshold(db)
    q = select(Float)
    if not sees_all(user):
        q = q.where(Float.manager_id == user.id)
    floats = list(db.scalars(q))

    def totals(fs):
        given = sum(f.amount_cents for f in fs)
        spent = sum(float_totals(f, th)["spent_cents"] for f in fs)
        exps = [e for f in fs for e in f.expenses]
        return {"floats": len(fs), "given": kes(given), "spent": kes(spent), "balance": kes(given - spent),
                "expenses": len(exps), "with_proof": sum(1 for e in exps if e.proof),
                "open": sum(1 for f in fs if f.status in ("OPEN", "QUERIED")),
                "awaiting": sum(1 for f in fs if f.status == "SUBMITTED"),
                "approved": sum(1 for f in fs if f.status == "APPROVED"),
                "queried": sum(1 for f in fs if f.status == "QUERIED")}

    out = {"me": totals([f for f in floats if f.manager_id == user.id]), "proof_threshold": kes(th)}
    if sees_all(user):
        out["all"] = totals(floats)
        by = {}
        for f in floats:
            by.setdefault(f.manager_id, []).append(f)
        people = db.scalars(select(User).where(User.role.in_(("admin", "manager"))).order_by(User.full_name))
        out["managers"] = [{"id": u.id, "name": u.full_name, "active": u.is_active, **totals(by.get(u.id, []))}
                           for u in people if u.is_active or u.id in by]
    return out
