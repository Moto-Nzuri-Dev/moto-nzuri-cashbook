"""Field & Office reports: written updates to the boss with photos, a decision request and replies."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import today
from ..database import get_db
from ..models import FieldReport, ReportPhoto, ReportReply, User
from ..pdf import field_report_pdf
from ..security import current_user, sees_all
from ..serialize import report_dict
from ..services import audit, parse_date, read_photo

router = APIRouter(prefix="/api/field-reports", tags=["field reports"])
KINDS = ("daily", "weekly", "one-off")


def _guard(user: User, r: FieldReport | None) -> FieldReport:
    if r is None or (not sees_all(user) and r.author_id != user.id):
        raise HTTPException(404, "Report not found.")
    return r


@router.get("")
def list_reports(db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(FieldReport).order_by(FieldReport.report_date.desc(), FieldReport.id.desc())
    if not sees_all(user):
        q = q.where(FieldReport.author_id == user.id)
    return [report_dict(r) for r in db.scalars(q)]


@router.post("")
def create_report(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if user.role == "boss":
        raise HTTPException(403, "The boss replies to reports rather than writing them.")
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "Give the report a title.")
    kind = body.get("kind") or "daily"
    if kind not in KINDS:
        raise HTTPException(400, "Kind must be daily, weekly or one-off.")
    d = parse_date(body.get("report_date") or today().isoformat(), "Report date")
    if d > today():
        raise HTTPException(400, "The report date can't be in the future.")
    r = FieldReport(author_id=user.id, kind=kind, report_date=d, title=title[:160],
                    body=(body.get("body") or "").strip(),
                    decision_needed=(body.get("decision_needed") or "").strip())
    db.add(r)
    db.flush()
    audit(db, user, "report_sent", f"#{r.id} {r.title}")
    db.commit()
    db.refresh(r)
    return report_dict(r, full=True)


@router.get("/{rid}")
def get_report(rid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return report_dict(_guard(user, db.get(FieldReport, rid)), full=True)


@router.post("/{rid}/photos")
async def add_photo(rid: int, file: UploadFile = File(...), caption: str = Form(""),
                    db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = _guard(user, db.get(FieldReport, rid))
    if r.author_id != user.id:
        raise HTTPException(403, "Only the person who wrote the report can add photos.")
    data, ctype = await read_photo(file)
    db.add(ReportPhoto(report_id=r.id, caption=caption.strip()[:160], data=data,
                       content_type=ctype, size=len(data)))
    db.commit()
    db.refresh(r)
    return report_dict(r, full=True)


@router.get("/{rid}/photos/{pid}")
def get_photo(rid: int, pid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _guard(user, db.get(FieldReport, rid))
    p = db.get(ReportPhoto, pid)
    if not p or p.report_id != rid:
        raise HTTPException(404, "Photo not found.")
    return Response(p.data, media_type=p.content_type, headers={"Cache-Control": "private, max-age=3600"})


@router.post("/{rid}/replies")
def reply(rid: int, body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = _guard(user, db.get(FieldReport, rid))
    text = (body.get("body") or "").strip()
    if not text:
        raise HTTPException(400, "Write a reply first.")
    db.add(ReportReply(report_id=r.id, author_id=user.id, body=text))
    audit(db, user, "report_reply", f"#{r.id}")
    db.commit()
    db.refresh(r)
    return report_dict(r, full=True)


@router.post("/{rid}/decision")
def decide(rid: int, body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = _guard(user, db.get(FieldReport, rid))
    if user.role not in ("boss", "admin") or r.author_id == user.id:
        raise HTTPException(403, "Only the boss can decide on someone else's report.")
    status = (body.get("status") or "").upper()
    if status not in ("APPROVED", "DECLINED", "NOTED"):
        raise HTTPException(400, "Decision must be APPROVED, DECLINED or NOTED.")
    r.status = status
    if (body.get("comment") or "").strip():
        db.add(ReportReply(report_id=r.id, author_id=user.id, body=f"[{status}] {body['comment'].strip()}"))
    audit(db, user, "report_" + status.lower(), f"#{r.id} {r.title}")
    db.commit()
    db.refresh(r)
    return report_dict(r, full=True)


@router.get("/{rid}/report.pdf")
def report_pdf(rid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = _guard(user, db.get(FieldReport, rid))
    return Response(field_report_pdf(r), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="report-{r.id}.pdf"'})
