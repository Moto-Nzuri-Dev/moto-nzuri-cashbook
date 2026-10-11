"""Database tables. All money is stored as whole cents (integers) to avoid rounding errors."""
from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .clock import now
from .database import Base

ROLES = ("admin", "manager", "boss")
FLOAT_STATUSES = ("OPEN", "SUBMITTED", "APPROVED", "QUERIED")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(10), default="manager")
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))


class Float(Base):
    __tablename__ = "floats"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    manager_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source: Mapped[str] = mapped_column(String(80), default="Boss")
    amount_cents: Mapped[int] = mapped_column(Integer)
    issued_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="OPEN")
    note: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    manager: Mapped[User] = relationship(foreign_keys=[manager_id])
    expenses: Mapped[list["Expense"]] = relationship(
        back_populates="float", cascade="all, delete-orphan", order_by="Expense.spent_on, Expense.id")
    reviews: Mapped[list["FloatReview"]] = relationship(
        cascade="all, delete-orphan", order_by="FloatReview.id")

    @property
    def code(self) -> str:
        return f"FLT-{self.id:04d}"


class FloatReview(Base):
    __tablename__ = "float_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    float_id: Mapped[int] = mapped_column(ForeignKey("floats.id"), index=True)
    decision: Mapped[str] = mapped_column(String(10))  # APPROVED | QUERIED
    comment: Mapped[str] = mapped_column(Text, default="")
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    reviewer: Mapped[User] = relationship()


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    float_id: Mapped[int] = mapped_column(ForeignKey("floats.id"), index=True)
    spent_on: Mapped[date] = mapped_column(Date)
    category: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(200))
    amount_cents: Mapped[int] = mapped_column(Integer)
    fee_cents: Mapped[int] = mapped_column(Integer, default=0)  # M-Pesa transaction cost
    mpesa_code: Mapped[str | None] = mapped_column(String(12), unique=True, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    float: Mapped[Float] = relationship(back_populates="expenses")
    proof: Mapped["Proof | None"] = relationship(
        back_populates="expense", cascade="all, delete-orphan", uselist=False)

    @property
    def total_cents(self) -> int:
        return self.amount_cents + self.fee_cents


class Proof(Base):
    __tablename__ = "proofs"
    __table_args__ = (UniqueConstraint("expense_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expenses.id"))
    kind: Mapped[str] = mapped_column(String(20), default="Receipt")  # Receipt | M-Pesa | Photo
    content_type: Mapped[str] = mapped_column(String(40), default="image/jpeg")
    size: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expense: Mapped[Expense] = relationship(back_populates="proof")


class FieldReport(Base):
    """Field & Office written updates to the boss, with photos and a reply thread."""
    __tablename__ = "field_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="daily")  # daily | weekly | one-off
    report_date: Mapped[date] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text, default="")
    decision_needed: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="SENT")  # SENT | APPROVED | DECLINED | NOTED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    author: Mapped[User] = relationship()
    photos: Mapped[list["ReportPhoto"]] = relationship(cascade="all, delete-orphan", order_by="ReportPhoto.id")
    replies: Mapped[list["ReportReply"]] = relationship(cascade="all, delete-orphan", order_by="ReportReply.id")


class ReportPhoto(Base):
    __tablename__ = "report_photos"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("field_reports.id"), index=True)
    caption: Mapped[str] = mapped_column(String(160), default="")
    content_type: Mapped[str] = mapped_column(String(40), default="image/jpeg")
    size: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary)


class ReportReply(Base):
    __tablename__ = "report_replies"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("field_reports.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    author: Mapped[User] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
