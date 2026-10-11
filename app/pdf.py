"""PDF output: the float evidence pack (every expense beside its proof) and field reports."""
import io
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .clock import now
from .models import FieldReport, Float
from .services import aware, float_totals, fmt_kes

BLUE, NAVY, CYAN = colors.HexColor("#0750A4"), colors.HexColor("#2B2A7C"), colors.HexColor("#00AEEF")
OK, WARN, BAD = colors.HexColor("#127a46"), colors.HexColor("#b45309"), colors.HexColor("#b42318")
LOGO = Path(__file__).parent / "static" / "logo.png"

ss = getSampleStyleSheet()
H = ParagraphStyle("h", parent=ss["Heading2"], textColor=NAVY, spaceAfter=4)
B = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=12.5)
SMALL = ParagraphStyle("s", parent=B, fontSize=8, textColor=colors.HexColor("#555555"))
STATUS_TEXT = {"OPEN": ("OPEN", WARN), "SUBMITTED": ("AWAITING BOSS", BLUE),
               "APPROVED": ("APPROVED", OK), "QUERIED": ("QUERIED", BAD)}


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def _header(canvas, doc, subtitle):
    w, h = A4
    canvas.saveState()
    canvas.setFillColor(BLUE)
    canvas.rect(0, h - 26 * mm, w, 26 * mm, stroke=0, fill=1)
    canvas.setFillColor(CYAN)
    canvas.rect(0, h - 27.5 * mm, w, 1.5 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.circle(22 * mm, h - 13 * mm, 9.5 * mm, stroke=0, fill=1)
    canvas.drawImage(str(LOGO), 13 * mm, h - 22 * mm, 18 * mm, 18 * mm, mask="auto")
    canvas.setFont("Helvetica-Bold", 17)
    canvas.drawString(36 * mm, h - 12 * mm, "MOTO NZURI")
    canvas.setFont("Helvetica", 9)
    canvas.drawString(36 * mm, h - 18 * mm, f"Sprinkle Solutions Ltd · {subtitle}")
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(15 * mm, 10 * mm, f"Generated {now():%d %b %Y %H:%M} · Moto Nzuri Cashbook")
    canvas.drawRightString(w - 15 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _doc(buf):
    return SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                             topMargin=33 * mm, bottomMargin=18 * mm)


def _photo(data: bytes, max_w=70 * mm, max_h=80 * mm):
    iw, ih = ImageReader(io.BytesIO(data)).getSize()
    s = min(max_w / iw, max_h / ih)  # fit inside the box, keeping the shape
    return Image(io.BytesIO(data), width=iw * s, height=ih * s)


def evidence_pack_pdf(f: Float, threshold: int) -> bytes:
    t = float_totals(f, threshold)
    buf = io.BytesIO()
    st_text, st_col = STATUS_TEXT[f.status]
    story = [
        Table([[Paragraph(f"<b>{_esc(f.label)}</b>", ParagraphStyle("t", parent=B, fontSize=14, leading=17)),
                Paragraph(f'<font color="{st_col.hexval()}"><b>{st_text}</b></font>',
                          ParagraphStyle("st", parent=B, fontSize=12, alignment=2))]],
              colWidths=[130 * mm, 50 * mm]),
        Paragraph(f"{f.code} · Manager: {_esc(f.manager.full_name)} · Float from {_esc(f.source)} "
                  f"on {f.issued_on:%d %b %Y}", SMALL),
        Spacer(1, 5 * mm),
    ]
    bal = t["balance_cents"]
    summary = Table([
        ["Float received", fmt_kes(f.amount_cents)],
        [f"Total spent ({t['expense_count']} expenses, incl. M-Pesa charges)", fmt_kes(t["spent_cents"])],
        ["Over by" if bal < 0 else "Balance", fmt_kes(abs(bal))],
        ["Proof attached", f"{t['proof_count']} of {t['expense_count']}"],
    ], colWidths=[110 * mm, 40 * mm])
    summary.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9.5), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONT", (0, 2), (-1, 2), "Helvetica-Bold", 10),
        ("TEXTCOLOR", (1, 2), (1, 2), BAD if bal < 0 else colors.black),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
    ]))
    story += [summary, Spacer(1, 4 * mm)]
    if f.note:
        story.append(Paragraph(f"<b>Manager's note:</b> {_esc(f.note)}", B))
    for r in f.reviews:
        word = "Approved" if r.decision == "APPROVED" else "Queried"
        story.append(Paragraph(f"<b>{word} by {_esc(r.reviewer.full_name)} on {aware(r.at):%d %b %Y}:</b> "
                               f"{_esc(r.comment) or '—'}", B))

    cats: dict[str, int] = {}
    for e in f.expenses:
        cats[e.category] = cats.get(e.category, 0) + e.total_cents
    if cats:
        story += [Spacer(1, 3 * mm), Paragraph("By category", H)]
        ct = Table([[c, fmt_kes(v)] for c, v in sorted(cats.items(), key=lambda x: -x[1])],
                   colWidths=[110 * mm, 40 * mm])
        ct.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 9), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                                ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#dddddd"))]))
        story.append(ct)

    story += [Spacer(1, 4 * mm), Paragraph("Expenses &amp; evidence", H)]
    for i, e in enumerate(f.expenses, 1):
        info = [Paragraph(f"<b>{i}. {_esc(e.description)}</b>", B),
                Paragraph(f"{e.spent_on:%d %b %Y} · {_esc(e.category)}"
                          + (f" · M-Pesa {e.mpesa_code}" if e.mpesa_code else ""), SMALL),
                Paragraph(f"<b>{fmt_kes(e.amount_cents)}</b>"
                          + (f" + charge {fmt_kes(e.fee_cents)} = <b>{fmt_kes(e.total_cents)}</b>" if e.fee_cents else ""),
                          ParagraphStyle("a", parent=B, fontSize=11, leading=15)),
                Paragraph(f"Proof: {e.proof.kind}" if e.proof else "No proof attached", SMALL)]
        if e.proof:
            right = _photo(e.proof.data)
        else:
            needed = e.total_cents >= threshold
            right = Table([[("NO PROOF — REQUIRED" if needed else "NO PROOF")]], colWidths=[70 * mm], rowHeights=[16 * mm])
            right.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1, BAD if needed else colors.grey),
                                       ("TEXTCOLOR", (0, 0), (-1, -1), BAD if needed else colors.grey),
                                       ("FONT", (0, 0), (-1, -1), "Helvetica-Bold", 9),
                                       ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        row = Table([[info, right]], colWidths=[105 * mm, 75 * mm])
        row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 6)]))
        story.append(KeepTogether(row))
    if not f.expenses:
        story.append(Paragraph("No expenses recorded yet.", B))

    doc = _doc(buf)
    hdr = lambda c, d: _header(c, d, "Float Evidence Pack")  # noqa: E731
    doc.build(story, onFirstPage=hdr, onLaterPages=hdr)
    return buf.getvalue()


def field_report_pdf(r: FieldReport) -> bytes:
    buf = io.BytesIO()
    story = [Paragraph(f"<b>{_esc(r.title)}</b>", ParagraphStyle("t", parent=B, fontSize=14, leading=17)),
             Paragraph(f"{r.kind.title()} report · {r.report_date:%d %b %Y} · by {_esc(r.author.full_name)} · "
                       f"Status: {r.status}", SMALL), Spacer(1, 4 * mm)]
    if r.body:
        story.append(Paragraph(_esc(r.body), B))
    if r.decision_needed:
        story += [Spacer(1, 3 * mm), Paragraph("Decision needed", H), Paragraph(_esc(r.decision_needed), B)]
    if r.photos:
        story += [Spacer(1, 3 * mm), Paragraph("Photos", H)]
        for p in r.photos:
            story.append(KeepTogether([_photo(p.data, 160 * mm, 110 * mm),
                                       Paragraph(_esc(p.caption), SMALL), Spacer(1, 3 * mm)]))
    if r.replies:
        story += [Spacer(1, 3 * mm), Paragraph("Replies", H)]
        for x in r.replies:
            story.append(Paragraph(f"<b>{_esc(x.author.full_name)}</b> ({aware(x.at):%d %b %H:%M}): {_esc(x.body)}", B))
    doc = _doc(buf)
    hdr = lambda c, d: _header(c, d, "Field & Office Report")  # noqa: E731
    doc.build(story, onFirstPage=hdr, onLaterPages=hdr)
    return buf.getvalue()
