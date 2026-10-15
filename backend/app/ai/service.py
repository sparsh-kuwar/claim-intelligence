"""
AI service: provider selection -> schema validation -> grounding/calibration.

Output of this module is a PREDICTION. It is stored in claims.ai_analysis and
never copied into the final record without passing validation.py + human review.
"""
import logging

from pydantic import ValidationError

from app.ai import rule_engine
from app.ai.llm import LLMError, call_anthropic, call_openai
from app.ai.prompts import PROMPT_VERSION
from app.config import Settings
from app.schemas import DECISION_CRITICAL_FIELDS, AIAnalysis

log = logging.getLogger(__name__)


def _ground(analysis: dict, description: str, form_model: str | None, form_serial: str | None) -> list[str]:
    """
    Post-hoc calibration: an LLM can be confidently wrong. If an identifier the model
    returned does not appear in the claim text OR the intake form, cap its confidence.
    """
    notes = []
    text = rule_engine.normalize_serial(description) or ""
    s = analysis["serialNumber"]
    if s["value"]:
        norm = rule_engine.normalize_serial(s["value"])
        if norm not in text and norm != rule_engine.normalize_serial(form_serial):
            s["confidence"] = min(s["confidence"], 40)
            notes.append("serialNumber not found in claim text or intake -> confidence capped at 40")
    m = analysis["equipmentModel"]
    if m["value"]:
        norm = rule_engine.normalize_model(m["value"])
        m["value"] = norm
        in_text = norm.replace("-", "") in text
        if not in_text and norm != rule_engine.normalize_model(form_model):
            m["confidence"] = min(m["confidence"], 40)
            notes.append("equipmentModel not found in claim text or intake -> confidence capped at 40")
    for f in analysis.values():
        if f["value"] in (None, ""):
            f["value"], f["confidence"] = None, 0
    return notes


def overall_confidence(analysis: dict) -> int:
    """Weakest-link: the claim is only as trustworthy as its least-certain decision-critical field."""
    scores = [analysis[f]["confidence"] for f in DECISION_CRITICAL_FIELDS if analysis[f]["value"] is not None]
    return min(scores) if scores else 0


def run_analysis(settings: Settings, description: str, form_model: str | None, form_serial: str | None,
                 form_warranty: str | None) -> tuple[dict, str, dict]:
    """Returns (analysis, provider_used, meta)."""
    claim = dict(description=description, form_model=form_model, form_serial=form_serial, form_warranty=form_warranty)
    provider = settings.ai_provider.lower()
    meta: dict = {"promptVersion": None, "fallbackReason": None, "groundingNotes": []}

    raw, used = None, "rule_based"
    if provider in ("anthropic", "openai"):
        try:
            raw = (call_anthropic if provider == "anthropic" else call_openai)(settings, **claim)
            AIAnalysis.model_validate(raw)
            used, meta["promptVersion"] = provider, PROMPT_VERSION
        except (LLMError, ValidationError, Exception) as e:  # never let AI failure block intake
            log.warning("LLM provider %s failed, falling back to rule engine: %s", provider, e)
            meta["fallbackReason"] = f"{provider} failed: {type(e).__name__}"
            raw, used = None, "rule_based (fallback)"
    if raw is None:
        raw = rule_engine.analyze(description, form_model, form_serial, form_warranty)

    analysis = AIAnalysis.model_validate(raw).model_dump()
    meta["groundingNotes"] = _ground(analysis, description, form_model, form_serial)
    return analysis, used, meta
