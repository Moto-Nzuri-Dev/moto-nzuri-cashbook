"""Shared helpers: money, settings, audit trail, photo compression, M-Pesa message parsing."""
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

from . import config
from .clock import TZ
from .models import AuditLog, Float, Setting, User

# ---------------------------------------------------------------- money

def to_cents(value, field="Amount", allow_zero=False) -> int:
    if value is None or value == "":
        if allow_zero:
            return 0
        raise HTTPException(400, f"{field} is required.")
    try:
        d = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        raise HTTPException(400, f"{field} must be a number.")
    if not d.is_finite():
        raise HTTPException(400, f"{field} must be a number.")
    cents = int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if cents < 0 or (cents == 0 and not allow_zero):
        raise HTTPException(400, f"{field} must be more than zero.")
    if cents > 100_000_000_00:
        raise HTTPException(400, f"{field} looks too large. Please check it.")
    return cents


def kes(cents: int) -> float:
    return round(cents / 100, 2)


def fmt_kes(cents: int) -> str:
    v = cents / 100
    return f"KES {v:,.0f}" if cents % 100 == 0 else f"KES {v:,.2f}"


def parse_date(value, field="Date") -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise HTTPException(400, f"{field} must be a date like 2026-09-20.")


def aware(dt: datetime | None) -> datetime | None:
    """SQLite drops time zones; treat stored naive times as Nairobi time."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=TZ)
    return dt

# ---------------------------------------------------------------- settings

def get_setting(db: Session, key: str, default: str) -> str:
    s = db.get(Setting, key)
    return s.value if s else default


def set_setting(db: Session, key: str, value: str) -> None:
    s = db.get(Setting, key)
    if s:
        s.value = value
    else:
        db.add(Setting(key=key, value=value))


def proof_threshold(db: Session) -> int:
    return int(get_setting(db, "proof_threshold_cents", str(config.DEFAULT_PROOF_THRESHOLD_CENTS)))

# ---------------------------------------------------------------- float maths

def float_totals(f: Float, threshold: int) -> dict:
    spent = sum(e.total_cents for e in f.expenses)
    missing = [e for e in f.expenses if e.proof is None and e.total_cents >= threshold]
    return {
        "spent_cents": spent,
        "balance_cents": f.amount_cents - spent,
        "expense_count": len(f.expenses),
        "proof_count": sum(1 for e in f.expenses if e.proof is not None),
        "missing_proof_count": len(missing),
        "missing_proof_ids": [e.id for e in missing],
    }

# ---------------------------------------------------------------- audit

def audit(db: Session, user: User | None, action: str, detail: str = "") -> None:
    db.add(AuditLog(user_id=user.id if user else None, action=action, detail=detail[:2000]))

# ---------------------------------------------------------------- photos

async def read_photo(file: UploadFile) -> tuple[bytes, str]:
    """Validate an uploaded image, fix its rotation and shrink it to ~250 KB JPEG."""
    raw = await file.read(config.MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise HTTPException(400, "The photo is empty.")
    if len(raw) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "That photo is too large (over 8 MB).")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, "That file is not a photo we can read. Use JPG or PNG.")
    if len(raw) <= config.PHOTO_TARGET_BYTES and img.format == "JPEG" \
            and max(img.size) <= config.PHOTO_MAX_SIDE:
        return raw, "image/jpeg"
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.convert("RGBA").split()[-1])
        img = bg
    side, quality, out = config.PHOTO_MAX_SIDE, 80, b""
    for _ in range(10):
        im = img.copy()
        im.thumbnail((side, side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality, optimize=True)
        out = buf.getvalue()
        if len(out) <= config.PHOTO_TARGET_BYTES:
            break
        if quality > 55:
            quality -= 10
        else:
            side = int(side * 0.8)
    return out, "image/jpeg"

# ---------------------------------------------------------------- M-Pesa

MPESA_CODE_RE = re.compile(r"^[A-Z0-9]{8,12}$")


def clean_mpesa_code(code: str | None) -> str | None:
    code = (code or "").strip().upper()
    if not code:
        return None
    if not MPESA_CODE_RE.match(code):
        raise HTTPException(400, "An M-Pesa code is 8–12 letters/numbers, e.g. QGH3XK21K0.")
    return code


def parse_mpesa_message(text: str) -> dict:
    """Pull code, amount, transaction cost, payee and date out of a pasted M-Pesa SMS."""
    s = " ".join((text or "").split())
    out: dict = {}
    m = re.search(r"\b([A-Z0-9]{8,12})\b\s+Confirmed", s, re.I) or re.match(r"\s*([A-Z0-9]{8,12})\b", s, re.I)
    if m:
        out["mpesa_code"] = m.group(1).upper()
    m = re.search(r"Ksh\s?([\d,]+(?:\.\d+)?)", s, re.I)
    if m:
        out["amount"] = float(m.group(1).replace(",", ""))
    m = re.search(r"Transaction cost,?\s*Ksh\s?([\d,]+(?:\.\d+)?)", s, re.I)
    if m:
        out["fee"] = float(m.group(1).replace(",", ""))
    m = re.search(r"(?:sent to|paid to)\s+(.+?)(?:\s+for account\s+.+?)?\s+on\s+\d", s, re.I)
    if m:
        out["payee"] = m.group(1).strip().rstrip(".")
    m = re.search(r"\bon\s+(\d{1,2})/(\d{1,2})/(\d{2,4})", s, re.I)
    if m:
        d, mo, y = m.groups()
        y = "20" + y if len(y) == 2 else y
        try:
            out["date"] = date(int(y), int(mo), int(d)).isoformat()
        except ValueError:
            pass
    return out
