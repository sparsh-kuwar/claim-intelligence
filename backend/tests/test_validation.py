"""Unit tests: business rules R1-R6, approval gate, final-value provenance."""
from datetime import date

import pytest

from app.ai.rule_engine import analyze
from app.validation import Intake, RegistryEntry, approval_blockers, evaluate, resolve_final_values

T = 80
CLEAN_TEXT = "Chiller CH-900 serial SN77310 is not cooling. Technician confirmed compressor failure. Under warranty."
REG_OK = RegistryEntry("SN77310", "CH-900", date(2024, 9, 1), date(2027, 8, 31))


def _intake(**kw):
    base = dict(equipment_model="CH-900", serial_number="SN77310", service_date=date(2026, 9, 18),
                warranty_status="UNDER_WARRANTY")
    base.update(kw)
    return Intake(**base)


def _rule(v, rid):
    return next(r for r in v["rules"] if r["id"] == rid)


@pytest.fixture
def clean():
    return analyze(CLEAN_TEXT, "CH-900", "SN77310", "UNDER_WARRANTY")


def test_clean_claim_is_ready_for_approval(clean):
    v = evaluate(_intake(), clean, REG_OK, T)
    assert v["outcome"] == "READY_FOR_APPROVAL", v["failedRules"]
    assert v["fieldsRequiringReview"] == []


def test_r1_missing_serial(clean):
    clean["serialNumber"] = {"value": None, "confidence": 0, "evidence": None}
    v = evaluate(_intake(serial_number=None), clean, None, T)
    assert not _rule(v, "R1")["passed"] and v["outcome"] == "NEEDS_REVIEW"
    assert "serialNumber" in v["flaggedFields"]


def test_r2_low_confidence(clean):
    clean["suspectedCause"]["confidence"] = 68
    v = evaluate(_intake(), clean, REG_OK, T)
    assert not _rule(v, "R2")["passed"]
    assert "suspectedCause" in v["fieldsRequiringReview"]


def test_r2_threshold_is_configurable(clean):
    clean["suspectedCause"]["confidence"] = 68
    assert evaluate(_intake(), clean, REG_OK, 60)["outcome"] == "READY_FOR_APPROVAL"


def test_r3_warranty_conflict(clean):
    expired = RegistryEntry("SN77310", "CH-900", date(2020, 1, 1), date(2022, 1, 1))
    v = evaluate(_intake(), clean, expired, T)
    assert not _rule(v, "R3")["passed"]
    assert v["registryWarrantyStatus"] == "EXPIRED"


def test_r3_unknown_serial_cannot_be_verified(clean):
    assert not _rule(evaluate(_intake(), clean, None, T), "R3")["passed"]


def test_r4_critical_severity(clean):
    clean["severity"] = {"value": "CRITICAL", "confidence": 99, "evidence": "smoke"}
    v = evaluate(_intake(), clean, REG_OK, T)
    assert not _rule(v, "R4")["passed"] and v["outcome"] == "NEEDS_REVIEW"


def test_r5_required_fields(clean):
    clean["suspectedCause"] = {"value": None, "confidence": 0, "evidence": None}
    assert not _rule(evaluate(_intake(), clean, REG_OK, T), "R5")["passed"]


def test_r6_model_mismatch(clean):
    v = evaluate(_intake(equipment_model="PX-150"), clean, REG_OK, T)
    assert not _rule(v, "R6")["passed"]


def test_final_values_carry_provenance(clean):
    reviews = {"resolution": {"action": "EDIT", "value": "Replace compressor + refrigerant recharge"},
               "affectedPart": {"action": "REJECT", "value": None}}
    final = resolve_final_values(clean, reviews, _intake(), "UNDER_WARRANTY")
    assert final["resolution"] == {"value": "Replace compressor + refrigerant recharge", "source": "HUMAN_EDITED",
                                   "aiConfidence": clean["resolution"]["confidence"]}
    assert final["affectedPart"]["value"] is None and final["affectedPart"]["source"] == "HUMAN_REJECTED"
    assert final["category"]["source"] == "AI_VALIDATED"
    assert final["warrantyRelevance"]["source"] == "WARRANTY_REGISTRY"


def test_needs_review_approval_requires_decisions_and_comment(clean):
    clean["suspectedCause"]["confidence"] = 60
    v = evaluate(_intake(), clean, REG_OK, T)
    final = resolve_final_values(clean, {}, _intake(), "UNDER_WARRANTY")
    blockers = approval_blockers("NEEDS_REVIEW", v, {}, final, None)
    assert any("suspectedCause" in b for b in blockers)
    assert any("comment" in b for b in blockers)


def test_rejected_required_field_blocks_approval(clean):
    v = evaluate(_intake(), clean, REG_OK, T)
    reviews = {"category": {"action": "REJECT", "value": None}}
    final = resolve_final_values(clean, reviews, _intake(), "UNDER_WARRANTY")
    assert any("category" in b for b in approval_blockers("READY_FOR_APPROVAL", v, reviews, final, None))
