"""
Database model.

Three layers are stored SEPARATELY on purpose:
  ai_analysis      -> raw AI prediction (value + confidence per field). Never the source of truth.
  validation       -> business-rule results computed from the AI output + DB facts.
  final columns    -> category, symptom, ... severity, confidence.
                      Written ONLY at approval time, from reviewer-validated values.
"""
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

JsonType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ClaimStatus:
    PROCESSING = "PROCESSING"                  # submitted, AI not run yet / running
    NEEDS_REVIEW = "NEEDS_REVIEW"              # at least one rule failed -> human must decide
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"  # all rules passed, confidence >= threshold
    APPROVED = "APPROVED"
    ESCALATED = "ESCALATED"
    ALL = [PROCESSING, NEEDS_REVIEW, READY_FOR_APPROVAL, APPROVED, ESCALATED]


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)

    # ---- intake (what the submitter told us) ----
    customer: Mapped[str] = mapped_column(String(200))
    equipment_model: Mapped[str] = mapped_column(String(100))
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str] = mapped_column(Text)
    service_date: Mapped[date] = mapped_column(Date)
    warranty_status: Mapped[str] = mapped_column(String(20))  # UNDER_WARRANTY | EXPIRED | UNKNOWN
    attachment_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachment_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ---- AI layer (prediction only) ----
    ai_analysis: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    ai_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ai_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ---- validation layer ----
    validation: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    field_reviews: Mapped[dict] = mapped_column(JsonType, default=dict)

    # ---- final, validated record (populated on approval only) ----
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    symptom: Mapped[str | None] = mapped_column(Text, nullable=True)
    suspected_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    affected_part: Mapped[str | None] = mapped_column(String(200), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # plain JSON (not JSONB) so exported key order is preserved exactly as built
    final_record: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    validation_status: Mapped[str] = mapped_column(String(30), default=ClaimStatus.PROCESSING, index=True)
    reviewer_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    events: Mapped[list["ClaimEvent"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", order_by="ClaimEvent.id"
    )


class ClaimEvent(Base):
    """Append-only audit trail: who/what changed a claim and why."""
    __tablename__ = "claim_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_pk: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    actor: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    claim: Mapped[Claim] = relationship(back_populates="events")


class WarrantyRecord(Base):
    """
    Manufacturer's warranty registry (system of record).
    Used by Rule 3: the claim/AI may SAY 'under warranty' - the registry decides.
    """
    __tablename__ = "warranty_registry"

    serial_number: Mapped[str] = mapped_column(String(100), primary_key=True)
    equipment_model: Mapped[str] = mapped_column(String(100))
    warranty_start: Mapped[date] = mapped_column(Date)
    warranty_end: Mapped[date] = mapped_column(Date)
