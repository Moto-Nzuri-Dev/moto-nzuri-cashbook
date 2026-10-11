"""Floats, expenses, proof photos, submit-to-boss and the boss's Approve / Query sign-off."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import config
from ..clock import now, today
from ..database import get_db
from ..models import Expense, Float, FloatReview, Proof, User
from ..pdf import evidence_pack_pdf
from ..security import can_hold_floats, current_user, guard_edit_float, guard_view_float, sees_all
from ..serialize import expense_dict, float_dict
from ..services import (audit, clean_mpesa_code, float_totals, fmt_kes, parse_date,
                        parse_mpesa_message, proof_threshold, read_photo, to_cents)

router = APIRouter(prefix="/api", tags=["floats"])


# ------------------------------------------------------------------ floats

@router.get("/floats")
def list_floats(manager_id: int | None = None, status: str | None = None,
                db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(Float).order_by(Float.issued_on.desc(), Float.id.desc())
    if not sees_all(user):
        q = q.where(Float.manager_id == user.id)
    elif manager_id:
        q = q.where(Float.manager_id == manager_id)
    if status:
        q = q.where(Float.status == status.upper())
    th = proof_threshold(db)
    return [float_dict(f, th) for f in db.scalars(q)]


@router.post("/floats")
def create_float(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not can_hold_floats(user):
        raise HTTPException(403, "Only managers and the administrator record floats.")
    manager_id = int(body.get("manager_id") or user.id)
    if manager_id != user.id and user.role != "admin":
        raise HTTPException(403, "You can only record floats you received yourself.")
    holder = db.get(User, manager_id)
    if not holder or not holder.is_active or not can_hold_floats(holder):
        raise HTTPException(400, "Choose an active manager to receive the float.")
    label = (body.get("label") or "").strip()
    if not label:
        raise HTTPException(400, "Give the float a name, e.g. 'Week float 13–18 Sep'.")
    issued = parse_date(body.get("issued_on") or today().isoformat(), "Float date")
    if issued > today():
        raise HTTPException(400, "The float date can't be in the future.")
    f = Float(label=label[:120], manager_id=holder.id, source=(body.get("source") or "Boss").strip()[:80],
              amount_cents=to_cents(body.get("amount"), "Float amount"), issued_on=issued,
              created_by=user.id)
    db.add(f)
    db.flush()
    audit(db, user, "float_created", f"{f.code} {label} {fmt_kes(f.amount_cents)} to {holder.full_name}")
    db.commit()
    return float_dict(f, proof_threshold(db), with_expenses=True)


@router.get("/floats/{fid}")
def get_float(fid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return float_dict(guard_view_float(user, db.get(Float, fid)), proof_threshold(db), with_expenses=True)


@router.patch("/floats/{fid}")
def update_float(fid: int, body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    f = guard_edit_float(user, db.get(Float, fid))
    if "label" in body and body["label"].strip():
        f.label = body["label"].strip()[:120]
    if "source" in body:
        f.source = (body["source"] or "").strip()[:80]
    if "amount" in body:
        f.amount_cents = to_cents(body["amount"], "Float amount")
    if "issued_on" in body:
        d = parse_date(body["issued_on"], "Float date")
        if d > today():
            raise HTTPException(400, "The float date can't be in the future.")
        f.issued_on = d
    audit(db, user, "float_updated", f"{f.code} {f.label} {fmt_kes(f.amount_cents)}")
    db.commit()
    return float_dict(f, proof_threshold(db), with_expenses=True)


@router.delete("/floats/{fid}")
def delete_float(fid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    f = guard_view_float(user, db.get(Float, fid))
    if user.role != "admin":
        guard_edit_float(user, f)
    if f.status == "APPROVED":
        raise HTTPException(409, "An approved float can't be deleted.")
    if f.expenses:
        raise HTTPException(409, "Delete or move this float's expenses first.")
    audit(db, user, "float_deleted", f"{f.code} {f.label}")
    db.delete(f)
    db.commit()
    return {"ok": True}


@router.post("/floats/{fid}/submit")
def submit_float(fid: int, body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    f = guard_edit_float(user, db.get(Float, fid))
    th = proof_threshold(db)
    t = float_totals(f, th)
    if t["missing_proof_count"]:
        raise HTTPException(409, f"{t['missing_proof_count']} expense(s) of {fmt_kes(th)} or more still need proof.")
    note = (body.get("note") or "").strip()
    if t["balance_cents"] != 0 and not note:
        raise HTTPException(400, "Add a note to the boss explaining the balance or overspend.")
    f.note = note
    f.status = "SUBMITTED"
    f.submitted_at = now()
    audit(db, user, "float_submitted", f"{f.code} spent {fmt_kes(t['spent_cents'])}, "
                                       f"balance {fmt_kes(t['balance_cents'])}")
    db.commit()
    return float_dict(f, th, with_expenses=True)


@router.post("/floats/{fid}/review")
def review_float(fid: int, body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if user.role not in ("boss", "admin"):
        raise HTTPException(403, "Only the boss can approve or query a float.")
    f = guard_view_float(user, db.get(Float, fid))
    if f.manager_id == user.id:
        raise HTTPException(403, "You can't approve or query your own float.")
    if f.status != "SUBMITTED":
        raise HTTPException(409, "Only a submitted float can be approved or queried.")
    decision = (body.get("decision") or "").upper()
    if decision not in ("APPROVED", "QUERIED"):
        raise HTTPException(400, "Decision must be APPROVED or QUERIED.")
    comment = (body.get("comment") or "").strip()
    if decision == "QUERIED" and not comment:
        raise HTTPException(400, "Write what needs fixing.")
    f.status = decision
    db.add(FloatReview(float_id=f.id, decision=decision, comment=comment, reviewer_id=user.id))
    audit(db, user, "float_" + decision.lower(), f"{f.code} {comment}")
    db.commit()
    db.refresh(f)
    return float_dict(f, proof_threshold(db), with_expenses=True)


@router.get("/floats/{fid}/evidence.pdf")
def evidence_pack(fid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    f = guard_view_float(user, db.get(Float, fid))
    pdf = evidence_pack_pdf(f, proof_threshold(db))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{f.code}-evidence-pack.pdf"'})


# ------------------------------------------------------------------ expenses

def _expense_fields(body: dict, e: Expense | None = None) -> dict:
    out = {}
    if e is None or "spent_on" in body:
        d = parse_date(body.get("spent_on") or today().isoformat(), "Expense date")
        if d > today():
            raise HTTPException(400, "The expense date can't be in the future.")
        out["spent_on"] = d
    if e is None or "description" in body:
        desc = (body.get("description") or "").strip()
        if not desc:
            raise HTTPException(400, "Add a short description.")
        out["description"] = desc[:200]
    if e is None or "category" in body:
        cat = body.get("category") or "Other"
        if cat not in config.CATEGORIES:
            raise HTTPException(400, "Pick a category from the list.")
        out["category"] = cat
    if e is None or "amount" in body:
        out["amount_cents"] = to_cents(body.get("amount"), "Amount")
    if e is None or "fee" in body:
        out["fee_cents"] = to_cents(body.get("fee"), "M-Pesa charge", allow_zero=True)
    if e is None or "mpesa_code" in body:
        out["mpesa_code"] = clean_mpesa_code(body.get("mpesa_code"))
    return out


def _check_duplicate_code(db: Session, code: str | None, exclude_id: int | None = None):
    if not code:
        return
    dup = db.scalar(select(Expense).where(Expense.mpesa_code == code))
    if dup and dup.id != exclude_id:
        raise HTTPException(409, f"M-Pesa code {code} is already recorded "
                                 f"({dup.description}, {fmt_kes(dup.amount_cents)}, {dup.spent_on}). "
                                 "Each M-Pesa transaction can only be claimed once.")


def _commit_expense(db: Session, e: Expense):
    try:
        db.commit()
    except IntegrityError:  # two people saving the same code at the same moment
        db.rollback()
        raise HTTPException(409, f"M-Pesa code {e.mpesa_code} is already recorded.")


def _guard_expense(db: Session, user: User, eid: int, edit: bool) -> Expense:
    e = db.get(Expense, eid)
    if e is None:
        raise HTTPException(404, "Expense not found.")
    (guard_edit_float if edit else guard_view_float)(user, e.float)
    return e


@router.post("/floats/{fid}/expenses")
def add_expense(fid: int, body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    f = guard_edit_float(user, db.get(Float, fid))
    fields = _expense_fields(body)
    _check_duplicate_code(db, fields["mpesa_code"])
    e = Expense(float_id=f.id, created_by=user.id, **fields)
    db.add(e)
    db.flush()
    audit(db, user, "expense_added", f"{f.code} #{e.id} {e.description} {fmt_kes(e.total_cents)}")
    _commit_expense(db, e)
    return expense_dict(e, proof_threshold(db))


@router.patch("/expenses/{eid}")
def update_expense(eid: int, body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = _guard_expense(db, user, eid, edit=True)
    before = f"{e.description} {fmt_kes(e.total_cents)}"
    fields = _expense_fields(body, e)
    if "mpesa_code" in fields:
        _check_duplicate_code(db, fields["mpesa_code"], exclude_id=e.id)
    for k, v in fields.items():
        setattr(e, k, v)
    audit(db, user, "expense_edited", f"#{e.id} was: {before}; now: {e.description} {fmt_kes(e.total_cents)}")
    _commit_expense(db, e)
    return expense_dict(e, proof_threshold(db))


@router.delete("/expenses/{eid}")
def delete_expense(eid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = _guard_expense(db, user, eid, edit=True)
    audit(db, user, "expense_deleted", f"{e.float.code} #{e.id} {e.description} {fmt_kes(e.total_cents)}")
    db.delete(e)
    db.commit()
    return {"ok": True}


@router.post("/expenses/{eid}/proof")
async def upload_proof(eid: int, file: UploadFile = File(...), kind: str = Form("Receipt"),
                       db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = _guard_expense(db, user, eid, edit=True)
    data, ctype = await read_photo(file)
    kind = kind if kind in ("Receipt", "M-Pesa", "Photo") else "Photo"
    if e.proof:
        e.proof.data, e.proof.content_type, e.proof.size, e.proof.kind = data, ctype, len(data), kind
    else:
        db.add(Proof(expense_id=e.id, data=data, content_type=ctype, size=len(data), kind=kind))
    audit(db, user, "proof_attached", f"#{e.id} {kind} {len(data)//1024} KB")
    db.commit()
    db.refresh(e)
    return expense_dict(e, proof_threshold(db))


@router.get("/expenses/{eid}/proof")
def get_proof(eid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = _guard_expense(db, user, eid, edit=False)
    if not e.proof:
        raise HTTPException(404, "No proof attached.")
    return Response(e.proof.data, media_type=e.proof.content_type,
                    headers={"Cache-Control": "private, max-age=3600"})


@router.delete("/expenses/{eid}/proof")
def delete_proof(eid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = _guard_expense(db, user, eid, edit=True)
    if e.proof:
        db.delete(e.proof)
        audit(db, user, "proof_removed", f"#{e.id}")
        db.commit()
    db.refresh(e)
    return expense_dict(e, proof_threshold(db))


@router.post("/tools/parse-mpesa")
def parse_mpesa(body: dict, user: User = Depends(current_user)):
    return parse_mpesa_message(body.get("text") or "")
