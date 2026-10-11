"""Turn database rows into the JSON the browser receives."""
from .models import Expense, FieldReport, Float, FloatReview, User
from .services import aware, float_totals, kes


def user_dict(u: User) -> dict:
    return {"id": u.id, "phone": u.phone, "full_name": u.full_name, "role": u.role, "is_active": u.is_active}


def review_dict(r: FloatReview) -> dict:
    return {"decision": r.decision, "comment": r.comment, "reviewer": r.reviewer.full_name,
            "at": aware(r.at).isoformat()}


def expense_dict(e: Expense, threshold: int) -> dict:
    return {
        "id": e.id, "float_id": e.float_id, "spent_on": e.spent_on.isoformat(),
        "category": e.category, "description": e.description,
        "amount": kes(e.amount_cents), "fee": kes(e.fee_cents), "total": kes(e.total_cents),
        "mpesa_code": e.mpesa_code,
        "proof": ({"kind": e.proof.kind, "size": e.proof.size} if e.proof else None),
        "needs_proof": e.proof is None and e.total_cents >= threshold,
    }


def float_dict(f: Float, threshold: int, with_expenses=False) -> dict:
    t = float_totals(f, threshold)
    d = {
        "id": f.id, "code": f.code, "label": f.label, "source": f.source,
        "manager_id": f.manager_id, "manager": f.manager.full_name,
        "amount": kes(f.amount_cents), "issued_on": f.issued_on.isoformat(),
        "status": f.status, "note": f.note,
        "submitted_at": aware(f.submitted_at).isoformat() if f.submitted_at else None,
        "spent": kes(t["spent_cents"]), "balance": kes(t["balance_cents"]),
        "expense_count": t["expense_count"], "proof_count": t["proof_count"],
        "missing_proof_count": t["missing_proof_count"],
        "reviews": [review_dict(r) for r in f.reviews],
    }
    if with_expenses:
        d["expenses"] = [expense_dict(e, threshold) for e in f.expenses]
    return d


def report_dict(r: FieldReport, full=False) -> dict:
    d = {
        "id": r.id, "kind": r.kind, "report_date": r.report_date.isoformat(), "title": r.title,
        "author_id": r.author_id, "author": r.author.full_name, "status": r.status,
        "decision_needed": r.decision_needed, "photo_count": len(r.photos),
        "reply_count": len(r.replies), "created_at": aware(r.created_at).isoformat(),
    }
    if full:
        d["body"] = r.body
        d["photos"] = [{"id": p.id, "caption": p.caption, "size": p.size} for p in r.photos]
        d["replies"] = [{"id": x.id, "author": x.author.full_name, "body": x.body,
                         "at": aware(x.at).isoformat()} for x in r.replies]
    return d
