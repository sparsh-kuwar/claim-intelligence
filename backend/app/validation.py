"""
Business validation engine. Pure functions, no DB/HTTP -> easy to unit test.

    AI Prediction -> Confidence -> Business Validation -> Final Status

Two gates:
  1. evaluate()          runs right after AI analysis and ROUTES the claim
                         (READY_FOR_APPROVAL vs NEEDS_REVIEW).
  2. approval_blockers() runs when someone clicks Approve and makes sure nothing
                         low-confidence / flagged / rejected is silently accepted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.ai.rule_engine import normalize_model, normalize_serial
from app.schemas import AI_FIELDS, DECISION_CRITICAL_FIELDS

REQUIRED_FINAL_FIELDS = ["category", "symptom", "suspectedCause", "severity", "resolution"]


@dataclass
class Intake:
    equipment_model: str | None
    serial_number: str | None
    service_date: date
    warranty_status: str


@dataclass
class RegistryEntry:
    serial_number: str
    equipment_model: str
    warranty_start: date
    warranty_end: date

    def status_on(self, d: date) -> str:
        return "UNDER_WARRANTY" if self.warranty_start <= d <= self.warranty_end else "EXPIRED"


def _rule(rule_id: str, name: str, passed: bool, message: str, fields: list[str] | None = None) -> dict:
    return {"id": rule_id, "name": name, "passed": passed, "message": message, "fields": fields or []}


def evaluate(intake: Intake, analysis: dict, registry: RegistryEntry | None, threshold: int) -> dict:
    rules: list[dict] = []
    serial = normalize_serial(intake.serial_number) or normalize_serial(analysis["serialNumber"]["value"])

    # R1 - missing serial number
    rules.append(_rule("R1", "Serial number present", bool(serial),
                       "Serial number present" if serial else "Serial number missing from intake and description",
                       [] if serial else ["serialNumber"]))

    # R2 - low AI confidence on any decision-critical field
    low = [f for f in DECISION_CRITICAL_FIELDS
           if analysis[f]["value"] is not None and analysis[f]["confidence"] < threshold]
    rules.append(_rule("R2", f"AI confidence >= {threshold}%", not low,
                       "All decision-critical fields meet threshold" if not low else
                       "Low confidence: " + ", ".join(f"{f} {analysis[f]['confidence']}%" for f in low), low))

    # R3 - warranty conflict (registry is the system of record)
    ai_w = analysis["warrantyRelevance"]["value"]
    if registry is None:
        rules.append(_rule("R3", "Warranty verified against registry", False,
                           "Serial not found in warranty registry - cannot verify coverage", ["warrantyRelevance"]))
    else:
        reg = registry.status_on(intake.service_date)
        claimed = {intake.warranty_status, ai_w} - {"UNKNOWN", None}
        conflict = "UNDER_WARRANTY" in claimed and reg == "EXPIRED"
        rules.append(_rule("R3", "Warranty verified against registry", not conflict,
                           f"Registry: {reg} on {intake.service_date} (ends {registry.warranty_end})" +
                           (f" but claim/AI says UNDER_WARRANTY" if conflict else ""),
                           ["warrantyRelevance"] if conflict else []))

    # R4 - critical severity always needs a human
    crit = analysis["severity"]["value"] == "CRITICAL"
    rules.append(_rule("R4", "Severity below CRITICAL", not crit,
                       "CRITICAL severity requires human sign-off" if crit else f"Severity {analysis['severity']['value']}",
                       ["severity"] if crit else []))

    # R5 - required fields extracted
    missing = [f for f in REQUIRED_FINAL_FIELDS if not analysis[f]["value"]]
    rules.append(_rule("R5", "Required fields extracted", not missing,
                       "All required fields present" if not missing else "Missing: " + ", ".join(missing), missing))

    # R6 - identity consistency (intake vs AI vs registry)
    problems, fields = [], []
    ai_model = normalize_model(analysis["equipmentModel"]["value"])
    form_model = normalize_model(intake.equipment_model)
    if ai_model and form_model and ai_model != form_model:
        problems.append(f"model: intake {form_model} vs description {ai_model}"); fields.append("equipmentModel")
    ai_serial = normalize_serial(analysis["serialNumber"]["value"])
    form_serial = normalize_serial(intake.serial_number)
    if ai_serial and form_serial and ai_serial != form_serial:
        problems.append(f"serial: intake {form_serial} vs description {ai_serial}"); fields.append("serialNumber")
    if registry and form_model and normalize_model(registry.equipment_model) != form_model:
        problems.append(f"registry says serial belongs to {registry.equipment_model}"); fields.append("equipmentModel")
    rules.append(_rule("R6", "Model/serial consistent", not problems,
                       "Intake, description and registry agree" if not problems else "; ".join(problems),
                       sorted(set(fields))))

    failed = [r for r in rules if not r["passed"]]
    flagged = sorted({f for r in failed for f in r["fields"]}, key=AI_FIELDS.index)
    # every field under threshold must be looked at by a human, critical or not
    must_review = sorted(set(flagged) | {f for f in AI_FIELDS
                                         if analysis[f]["value"] is not None and analysis[f]["confidence"] < threshold},
                         key=AI_FIELDS.index)
    return {
        "threshold": threshold,
        "rules": rules,
        "outcome": "READY_FOR_APPROVAL" if not failed else "NEEDS_REVIEW",
        "failedRules": [r["id"] for r in failed],
        "flaggedFields": flagged,
        "fieldsRequiringReview": must_review if failed else [],
        "registryWarrantyStatus": registry.status_on(intake.service_date) if registry else None,
    }


def resolve_final_values(analysis: dict, reviews: dict, intake: Intake, registry_status: str | None) -> dict:
    """
    Build the validated record. Each field carries provenance so the export shows
    exactly which values a human touched.
    """
    final: dict[str, dict] = {}
    for f in AI_FIELDS:
        ai = analysis[f]
        r = reviews.get(f)
        if r is None:
            final[f] = {"value": ai["value"], "source": "AI_VALIDATED", "aiConfidence": ai["confidence"]}
        elif r["action"] == "ACCEPT":
            final[f] = {"value": ai["value"], "source": "HUMAN_ACCEPTED", "aiConfidence": ai["confidence"]}
        elif r["action"] == "EDIT":
            final[f] = {"value": r["value"].strip(), "source": "HUMAN_EDITED", "aiConfidence": ai["confidence"]}
        else:
            final[f] = {"value": None, "source": "HUMAN_REJECTED", "aiConfidence": ai["confidence"]}
    if final["severity"]["value"]:
        final["severity"]["value"] = final["severity"]["value"].upper()
    # identity: intake form wins over AI unless a reviewer edited it
    if final["serialNumber"]["source"] != "HUMAN_EDITED" and intake.serial_number:
        final["serialNumber"] = {"value": normalize_serial(intake.serial_number), "source": "INTAKE",
                                 "aiConfidence": analysis["serialNumber"]["confidence"]}
    if final["equipmentModel"]["source"] != "HUMAN_EDITED":
        final["equipmentModel"] = {"value": normalize_model(intake.equipment_model), "source": "INTAKE",
                                   "aiConfidence": analysis["equipmentModel"]["confidence"]}
    # warranty: registry is the system of record
    if registry_status and final["warrantyRelevance"]["source"] != "HUMAN_EDITED":
        final["warrantyRelevance"] = {"value": registry_status, "source": "WARRANTY_REGISTRY",
                                      "aiConfidence": analysis["warrantyRelevance"]["confidence"]}
    return final


def approval_blockers(status: str, validation: dict, reviews: dict, final: dict, comment: str | None) -> list[str]:
    blockers: list[str] = []
    if status == "NEEDS_REVIEW":
        pending = [f for f in validation.get("fieldsRequiringReview", []) if f not in reviews]
        if pending:
            blockers.append("Review decision required for: " + ", ".join(pending))
        if not (comment and comment.strip()):
            blockers.append("Reviewer comment is required to approve a claim that failed validation")
    for f in REQUIRED_FINAL_FIELDS:
        if not final[f]["value"]:
            blockers.append(f"{f} has no validated value (rejected or missing) - edit it or escalate")
    if not final["serialNumber"]["value"]:
        blockers.append("serialNumber is required - enter it or escalate")
    return blockers
