"""Claim API routes."""
import os
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.ai.service import overall_confidence, run_analysis
from app.config import get_settings
from app.database import get_db
from app.errors import ApiError, _clean_validation_errors
from app.models import Claim, ClaimEvent, ClaimStatus, WarrantyRecord
from app.schemas import (ClaimCreate, ClaimDetailOut, ClaimOut, ClaimSummaryOut, DecisionRequest, EscalateRequest,
                         ReviewRequest)
from app.validation import Intake, RegistryEntry, approval_blockers, evaluate, resolve_final_values

router = APIRouter(prefix="/api/claims", tags=["claims"])

ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".txt", ".log", ".csv"}
CLAIM_ID_RE = re.compile(r"^CLM-\d{5,}$")


# ----------------------------------------------------------------- helpers

def _get(db: Session, claim_id: str, with_events: bool = False) -> Claim:
    if not CLAIM_ID_RE.match(claim_id):
        raise ApiError(400, "BAD_CLAIM_ID", "Claim ID must look like CLM-10001")
    q = select(Claim).where(Claim.claim_id == claim_id)
    if with_events:
        q = q.options(selectinload(Claim.events))
    claim = db.scalar(q)
    if not claim:
        raise ApiError(404, "NOT_FOUND", f"Claim {claim_id} not found")
    return claim


def _event(db: Session, claim: Claim, event_type: str, actor: str, **details) -> None:
    db.add(ClaimEvent(claim_pk=claim.id, event_type=event_type, actor=actor, details=details))


def _intake(c: Claim) -> Intake:
    return Intake(c.equipment_model, c.serial_number, c.service_date, c.warranty_status)


def _registry(db: Session, serial: str | None) -> RegistryEntry | None:
    from app.ai.rule_engine import normalize_serial
    s = normalize_serial(serial)
    if not s:
        return None
    rec = db.get(WarrantyRecord, s)
    return RegistryEntry(rec.serial_number, rec.equipment_model, rec.warranty_start, rec.warranty_end) if rec else None


def _detail(db: Session, claim_id: str) -> dict:
    db.expire_all()
    return ClaimDetailOut.model_validate(_get(db, claim_id, with_events=True)).model_dump(by_alias=True, mode="json")


def _require_status(claim: Claim, allowed: list[str], action: str) -> None:
    if claim.validation_status not in allowed:
        raise ApiError(409, "INVALID_STATE",
                       f"Cannot {action} a claim in status {claim.validation_status}; allowed: {', '.join(allowed)}")


# ----------------------------------------------------------------- intake

CREATE_BODY = {
    "requestBody": {"required": True, "content": {
        "application/json": {"schema": ClaimCreate.model_json_schema(by_alias=True)},
        "multipart/form-data": {"schema": {"type": "object", "properties": {
            **{k: {"type": "string"} for k in ["customer", "equipmentModel", "serialNumber", "description",
                                               "serviceDate", "warrantyStatus"]},
            "attachment": {"type": "string", "format": "binary"}}}},
    }}
}


@router.post("", status_code=201, openapi_extra=CREATE_BODY, summary="Submit a new service claim")
async def create_claim(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    ctype = request.headers.get("content-type", "")
    upload = None
    if ctype.startswith("application/json"):
        try:
            data = await request.json()
        except Exception:
            raise ApiError(400, "BAD_JSON", "Body is not valid JSON")
    elif ctype.startswith("multipart/form-data") or ctype.startswith("application/x-www-form-urlencoded"):
        form = await request.form()
        data = {k: v for k, v in form.items() if k != "attachment"}
        a = form.get("attachment")
        upload = a if getattr(a, "filename", None) else None
    else:
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "Use application/json or multipart/form-data")

    try:
        payload = ClaimCreate.model_validate(data)
    except ValidationError as e:
        raise ApiError(422, "VALIDATION_ERROR", "Claim validation failed", _clean_validation_errors(e.errors()))

    content, safe_name = None, None
    if upload is not None:
        ext = os.path.splitext(upload.filename)[1].lower()
        if ext not in ALLOWED_EXT:
            raise ApiError(422, "BAD_ATTACHMENT", f"Attachment type {ext or '?'} not allowed ({', '.join(sorted(ALLOWED_EXT))})")
        content = await upload.read()
        if len(content) > settings.max_upload_mb * 1024 * 1024:
            raise ApiError(413, "ATTACHMENT_TOO_LARGE", f"Attachment exceeds {settings.max_upload_mb} MB")
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(upload.filename))[:120]

    claim = Claim(customer=payload.customer, equipment_model=payload.equipment_model,
                  serial_number=payload.serial_number, description=payload.description,
                  service_date=payload.service_date, warranty_status=payload.warranty_status,
                  validation_status=ClaimStatus.PROCESSING, field_reviews={})
    db.add(claim)
    db.flush()
    claim.claim_id = f"CLM-{10000 + claim.id}"
    if content is not None:
        os.makedirs(settings.upload_dir, exist_ok=True)
        path = os.path.join(settings.upload_dir, f"{claim.claim_id}_{uuid.uuid4().hex[:8]}_{safe_name}")
        with open(path, "wb") as fh:
            fh.write(content)
        claim.attachment_name, claim.attachment_path = safe_name, path
    _event(db, claim, "SUBMITTED", "intake", attachment=safe_name)
    db.commit()
    return {
        "claimId": claim.claim_id,
        "customer": claim.customer,
        "equipmentModel": claim.equipment_model,
        "serialNumber": claim.serial_number,
        "status": claim.validation_status,
        "submittedAt": claim.created_at.isoformat(),
    }


@router.get("", summary="List claims (filter by status, search)")
def list_claims(status: str | None = Query(None), search: str | None = Query(None, max_length=100),
                limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    q = select(Claim)
    if status:
        if status not in ClaimStatus.ALL:
            raise ApiError(400, "BAD_STATUS", f"status must be one of {ClaimStatus.ALL}")
        q = q.where(Claim.validation_status == status)
    if search:
        like = f"%{search}%"
        q = q.where(or_(Claim.claim_id.ilike(like), Claim.customer.ilike(like),
                        Claim.equipment_model.ilike(like), Claim.serial_number.ilike(like)))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(Claim.id.desc()).limit(limit).offset(offset)).all()
    counts = dict(db.execute(select(Claim.validation_status, func.count()).group_by(Claim.validation_status)).all())
    items = []
    for c in rows:
        s = ClaimSummaryOut.model_validate(c)
        if c.ai_analysis:
            s.severity_hint = c.severity or c.ai_analysis["severity"]["value"]
            s.category_hint = c.category or c.ai_analysis["category"]["value"]
        items.append(s.model_dump(by_alias=True, mode="json"))
    return {"items": items, "total": total, "counts": {s: counts.get(s, 0) for s in ClaimStatus.ALL}}


@router.get("/{claim_id}", summary="Get full claim incl. AI output, validation, reviews, audit trail")
def get_claim(claim_id: str, db: Session = Depends(get_db)):
    return _detail(db, claim_id)


@router.get("/{claim_id}/attachment", summary="Download the claim attachment")
def get_attachment(claim_id: str, db: Session = Depends(get_db)):
    c = _get(db, claim_id)
    if not c.attachment_path or not os.path.exists(c.attachment_path):
        raise ApiError(404, "NO_ATTACHMENT", "Claim has no attachment")
    return FileResponse(c.attachment_path, filename=c.attachment_name)


# ----------------------------------------------------------------- AI + validation

@router.post("/{claim_id}/analyze", summary="Run AI extraction + business validation, route the claim")
def analyze_claim(claim_id: str, db: Session = Depends(get_db)):
    settings = get_settings()
    c = _get(db, claim_id)
    _require_status(c, [ClaimStatus.PROCESSING, ClaimStatus.NEEDS_REVIEW, ClaimStatus.READY_FOR_APPROVAL], "analyze")

    analysis, provider, meta = run_analysis(settings, c.description, c.equipment_model, c.serial_number, c.warranty_status)
    registry = _registry(db, c.serial_number or analysis["serialNumber"]["value"])
    validation = evaluate(_intake(c), analysis, registry, settings.confidence_threshold)
    validation["aiMeta"] = meta

    c.ai_analysis, c.ai_provider, c.ai_confidence = analysis, provider, overall_confidence(analysis)
    c.validation, c.field_reviews = validation, {}
    c.validation_status = validation["outcome"]
    _event(db, c, "AI_ANALYZED", f"ai:{provider}", overallConfidence=c.ai_confidence, meta=meta)
    _event(db, c, "VALIDATED", "rule-engine", outcome=validation["outcome"], failedRules=validation["failedRules"])
    db.commit()
    return _detail(db, claim_id)


@router.get("/{claim_id}/analysis", summary="AI prediction + validation result only")
def get_analysis(claim_id: str, db: Session = Depends(get_db)):
    c = _get(db, claim_id)
    if not c.ai_analysis:
        raise ApiError(409, "NOT_ANALYZED", "Claim has not been analyzed yet; POST /analyze first")
    return {"claimId": c.claim_id, "aiProvider": c.ai_provider, "aiConfidence": c.ai_confidence,
            "analysis": c.ai_analysis, "validation": c.validation, "status": c.validation_status}


# ----------------------------------------------------------------- human in the loop

@router.patch("/{claim_id}/review", summary="Accept / edit / reject individual AI values, add comment")
def review_claim(claim_id: str, body: ReviewRequest, db: Session = Depends(get_db)):
    c = _get(db, claim_id)
    _require_status(c, [ClaimStatus.NEEDS_REVIEW, ClaimStatus.READY_FOR_APPROVAL], "review")
    reviews = dict(c.field_reviews or {})
    changes = {}
    for field, r in body.field_reviews.items():
        entry = {"action": r.action, "value": r.value.strip() if r.value else None,
                 "reviewer": body.reviewer, "at": datetime.now(timezone.utc).isoformat()}
        if field == "severity" and entry["value"]:
            entry["value"] = entry["value"].upper()
        reviews[field] = entry
        changes[field] = {"action": r.action, "aiValue": c.ai_analysis[field]["value"], "newValue": entry["value"]}
    c.field_reviews = reviews
    if body.comment:
        c.reviewer_comment = body.comment.strip()
    c.reviewed_by = body.reviewer
    _event(db, c, "REVIEWED", body.reviewer, changes=changes, comment=body.comment)
    db.commit()
    return _detail(db, claim_id)


@router.post("/{claim_id}/approve", summary="Approve: builds and stores the validated record")
def approve_claim(claim_id: str, body: DecisionRequest, db: Session = Depends(get_db)):
    c = _get(db, claim_id)
    _require_status(c, [ClaimStatus.NEEDS_REVIEW, ClaimStatus.READY_FOR_APPROVAL], "approve")
    comment = (body.comment or c.reviewer_comment or "").strip() or None
    final = resolve_final_values(c.ai_analysis, c.field_reviews or {}, _intake(c),
                                 c.validation.get("registryWarrantyStatus"))
    blockers = approval_blockers(c.validation_status, c.validation, c.field_reviews or {}, final, comment)
    if blockers:
        raise ApiError(422, "APPROVAL_BLOCKED", "Claim cannot be approved yet", blockers)

    was = c.validation_status
    c.category = final["category"]["value"]
    c.symptom = final["symptom"]["value"]
    c.suspected_cause = final["suspectedCause"]["value"]
    c.affected_part = final["affectedPart"]["value"]
    c.severity = final["severity"]["value"]
    c.resolution = final["resolution"]["value"]
    c.confidence = c.ai_confidence
    c.reviewer_comment, c.reviewed_by = comment, body.reviewer
    c.validation_status = ClaimStatus.APPROVED
    now = datetime.now(timezone.utc)
    human_touched = [f for f, v in final.items() if v["source"].startswith("HUMAN")]
    c.final_record = {
        "claimId": c.claim_id,
        "customer": c.customer,
        "equipmentModel": final["equipmentModel"]["value"],
        "serialNumber": final["serialNumber"]["value"],
        "serviceDate": c.service_date.isoformat(),
        "warrantyStatus": final["warrantyRelevance"]["value"],
        "category": c.category,
        "symptom": c.symptom,
        "suspectedCause": c.suspected_cause,
        "affectedPart": c.affected_part,
        "severity": c.severity,
        "resolution": c.resolution,
        "confidence": c.ai_confidence,
        "status": ClaimStatus.APPROVED,
        "approvalPath": "HUMAN_REVIEW" if was == ClaimStatus.NEEDS_REVIEW else "AUTO_ELIGIBLE",
        "humanVerifiedFields": human_touched,
        "failedRulesAtIntake": c.validation.get("failedRules", []),
        "provenance": {f: {"source": v["source"], "aiConfidence": v["aiConfidence"]} for f, v in final.items()},
        "reviewer": body.reviewer,
        "reviewerComment": comment,
        "aiProvider": c.ai_provider,
        "approvedAt": now.isoformat(),
    }
    _event(db, c, "APPROVED", body.reviewer, approvalPath=c.final_record["approvalPath"], comment=comment)
    db.commit()
    return _detail(db, claim_id)


@router.post("/{claim_id}/escalate", summary="Escalate to Tier-2 / engineering with a reason")
def escalate_claim(claim_id: str, body: EscalateRequest, db: Session = Depends(get_db)):
    c = _get(db, claim_id)
    _require_status(c, [ClaimStatus.NEEDS_REVIEW, ClaimStatus.READY_FOR_APPROVAL], "escalate")
    c.validation_status = ClaimStatus.ESCALATED
    c.reviewer_comment, c.reviewed_by = body.reason.strip(), body.reviewer
    _event(db, c, "ESCALATED", body.reviewer, reason=body.reason)
    db.commit()
    return _detail(db, claim_id)


# ----------------------------------------------------------------- output

@router.get("/{claim_id}/export", summary="Export the validated record (approved claims only)")
def export_claim(claim_id: str, download: bool = False, db: Session = Depends(get_db)):
    c = _get(db, claim_id)
    if c.validation_status != ClaimStatus.APPROVED or not c.final_record:
        raise ApiError(409, "NOT_VALIDATED",
                       f"Only APPROVED claims can be exported (current: {c.validation_status}). "
                       "Unvalidated AI output is never exported as a final record.")
    headers = {"Content-Disposition": f'attachment; filename="{c.claim_id}.json"'} if download else None
    return JSONResponse(content=c.final_record, headers=headers)
