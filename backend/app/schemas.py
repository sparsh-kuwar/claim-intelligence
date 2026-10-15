"""Pydantic request/response schemas (API contract + input validation)."""
import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

WarrantyStatus = Literal["UNDER_WARRANTY", "EXPIRED", "UNKNOWN"]
Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]

CATEGORIES = [
    "Hardware Failure",
    "Power/Electrical",
    "Connectivity/Network",
    "Software/Firmware",
    "Overheating/Thermal",
    "Mechanical Wear",
    "Physical Damage",
    "Installation/Configuration",
    "Safety Hazard",
    "Other",
]

# Fields the AI produces. Order = display order.
AI_FIELDS = [
    "equipmentModel",
    "serialNumber",
    "category",
    "symptom",
    "suspectedCause",
    "affectedPart",
    "severity",
    "resolution",
    "warrantyRelevance",
]

# Fields whose confidence drives routing (Rule 2). A wrong value here changes
# money/parts/safety decisions, so each one must clear the threshold.
DECISION_CRITICAL_FIELDS = ["equipmentModel", "serialNumber", "category", "suspectedCause", "severity", "resolution"]

_SAFE_TEXT = re.compile(r"^[\w\s.,:;!?'\"()/&@#%+\-]*$", re.UNICODE)


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class ClaimCreate(CamelModel):
    customer: str = Field(min_length=2, max_length=200)
    equipment_model: str = Field(min_length=1, max_length=100)
    serial_number: str | None = Field(default=None, max_length=100)
    description: str = Field(min_length=10, max_length=5000)
    service_date: date
    warranty_status: WarrantyStatus

    @field_validator("customer", "equipment_model", "serial_number", "description", mode="before")
    @classmethod
    def strip(cls, v, info):
        if isinstance(v, str):
            v = v.strip()
            if info.field_name == "serial_number" and not v:
                return None
        return v

    @field_validator("customer", "equipment_model", "serial_number")
    @classmethod
    def no_markup(cls, v):
        if v is not None and not _SAFE_TEXT.match(v):
            raise ValueError("contains unsupported characters")
        return v

    @field_validator("service_date")
    @classmethod
    def not_future(cls, v: date):
        if v > date.today():
            raise ValueError("service date cannot be in the future")
        return v


class AIField(BaseModel):
    value: str | None
    confidence: int = Field(ge=0, le=100)
    evidence: str | None = None


class AIAnalysis(BaseModel):
    """Strict schema every AI provider's output must pass before we store it."""
    equipmentModel: AIField
    serialNumber: AIField
    category: AIField
    symptom: AIField
    suspectedCause: AIField
    affectedPart: AIField
    severity: AIField
    resolution: AIField
    warrantyRelevance: AIField

    @field_validator("category")
    @classmethod
    def valid_category(cls, f: AIField):
        if f.value is not None and f.value not in CATEGORIES:
            f.value = "Other"
            f.confidence = min(f.confidence, 50)
        return f

    @field_validator("severity")
    @classmethod
    def valid_severity(cls, f: AIField):
        if f.value is not None:
            f.value = f.value.upper()
            if f.value not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                f.value, f.confidence = None, 0
        return f

    @field_validator("warrantyRelevance")
    @classmethod
    def valid_warranty(cls, f: AIField):
        if f.value not in {"UNDER_WARRANTY", "EXPIRED", "UNKNOWN", None}:
            f.value, f.confidence = "UNKNOWN", min(f.confidence, 40)
        return f


ReviewAction = Literal["ACCEPT", "EDIT", "REJECT"]


class FieldReview(BaseModel):
    action: ReviewAction
    value: str | None = Field(default=None, max_length=2000)


class ReviewRequest(CamelModel):
    reviewer: str = Field(default="reviewer", min_length=1, max_length=100)
    field_reviews: dict[str, FieldReview] = Field(default_factory=dict)
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("field_reviews")
    @classmethod
    def known_fields(cls, v: dict[str, FieldReview]):
        unknown = set(v) - set(AI_FIELDS)
        if unknown:
            raise ValueError(f"unknown field(s): {sorted(unknown)}")
        for name, r in v.items():
            if r.action == "EDIT" and not (r.value and r.value.strip()):
                raise ValueError(f"{name}: EDIT requires a non-empty value")
            if name == "severity" and r.action == "EDIT" and r.value.upper() not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                raise ValueError("severity must be LOW, MEDIUM, HIGH or CRITICAL")
            if name == "category" and r.action == "EDIT" and r.value not in CATEGORIES:
                raise ValueError(f"category must be one of {CATEGORIES}")
        return v


class DecisionRequest(CamelModel):
    reviewer: str = Field(default="reviewer", min_length=1, max_length=100)
    comment: str | None = Field(default=None, max_length=2000)


class EscalateRequest(CamelModel):
    reviewer: str = Field(default="reviewer", min_length=1, max_length=100)
    reason: str = Field(min_length=3, max_length=2000)


class EventOut(CamelModel):
    event_type: str
    actor: str
    details: dict
    created_at: datetime


class ClaimOut(CamelModel):
    claim_id: str
    customer: str
    equipment_model: str
    serial_number: str | None
    description: str
    service_date: date
    warranty_status: str
    attachment_name: str | None
    ai_analysis: dict | None
    ai_provider: str | None
    ai_confidence: int | None
    validation: dict | None
    field_reviews: dict
    category: str | None
    symptom: str | None
    suspected_cause: str | None
    affected_part: str | None
    severity: str | None
    resolution: str | None
    confidence: int | None
    validation_status: str
    reviewer_comment: str | None
    reviewed_by: str | None
    created_at: datetime
    updated_at: datetime


class ClaimDetailOut(ClaimOut):
    events: list[EventOut] = []


class ClaimSummaryOut(CamelModel):
    claim_id: str
    customer: str
    equipment_model: str
    serial_number: str | None
    validation_status: str
    ai_confidence: int | None
    severity_hint: str | None = None
    category_hint: str | None = None
    created_at: datetime
