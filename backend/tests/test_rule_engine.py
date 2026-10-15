"""Unit tests: AI extraction (rule-based engine) + grounding."""
from app.ai.rule_engine import analyze, normalize_model, normalize_serial
from app.ai.service import _ground, overall_confidence

EXAMPLE = ("Router AX500 has intermittent connectivity. Customer replaced the power module twice. "
           "Device is still under warranty. Technician suspects a hardware failure.")


def test_pdf_example_extraction():
    a = analyze(EXAMPLE, "AX-500", "SN10231", "UNDER_WARRANTY")
    assert a["equipmentModel"]["value"] == "AX-500" and a["equipmentModel"]["confidence"] >= 95
    assert a["serialNumber"]["value"] == "SN10231"
    assert a["category"]["value"] == "Hardware Failure"
    assert a["symptom"]["value"] == "Intermittent connectivity"
    assert a["affectedPart"]["value"] == "Power Module"
    assert a["suspectedCause"]["value"] == "Power Module failure"
    assert a["severity"]["value"] == "HIGH"
    assert a["warrantyRelevance"]["value"] == "UNDER_WARRANTY"


def test_replaced_part_that_did_not_fix_issue_lowers_cause_confidence():
    a = analyze(EXAMPLE, "AX-500", "SN10231", "UNDER_WARRANTY")
    assert a["suspectedCause"]["confidence"] < 80
    assert "already replaced" in a["suspectedCause"]["evidence"]


def test_confirmed_diagnosis_is_high_confidence():
    a = analyze("Chiller not cooling. Technician confirmed compressor failure.", "CH-900", "SN77310", None)
    assert a["suspectedCause"]["value"] == "Compressor failure"
    assert a["suspectedCause"]["confidence"] >= 90


def test_safety_keywords_force_critical():
    a = analyze("Unit is smoking and there are sparks from the power supply.", "LX-220", "SN55501", None)
    assert a["severity"]["value"] == "CRITICAL"
    assert a["category"]["value"] == "Safety Hazard"


def test_negated_warranty_is_expired():
    a = analyze("Device does not power on. It is out of warranty.", "AX-500", "SN1", "UNDER_WARRANTY")
    assert a["warrantyRelevance"]["value"] == "EXPIRED"


def test_still_under_warranty_is_not_treated_as_persisting_issue():
    a = analyze("Technician confirmed antenna failure. Device is still under warranty.", "AX-700", "SN20417", None)
    assert "already replaced" not in a["suspectedCause"]["evidence"]


def test_missing_serial_returns_null_not_invented():
    a = analyze("Display flickers. Technician suspects display failure.", "PX-150", None, None)
    assert a["serialNumber"]["value"] is None
    assert a["serialNumber"]["confidence"] == 0


def test_model_mismatch_lowers_confidence():
    a = analyze("Unit RX-300 reboots repeatedly.", "PX-150", "SN88120", None)
    assert a["equipmentModel"]["value"] == "RX-300"
    assert a["equipmentModel"]["confidence"] < 80


def test_vague_text_gives_low_confidence():
    a = analyze("The machine is acting weird sometimes.", "RX-300", "SN90001", None)
    assert a["suspectedCause"]["value"] is None
    assert a["category"]["confidence"] < 80


def test_normalizers():
    assert normalize_model("ax500") == "AX-500"
    assert normalize_model("AX 500") == "AX-500"
    assert normalize_serial("sn-10231") == "SN10231"


def test_grounding_caps_hallucinated_serial():
    a = analyze("Router AX500 has intermittent connectivity.", "AX-500", "SN10231", None)
    a["serialNumber"]["value"], a["serialNumber"]["confidence"] = "SN99999", 95   # LLM made it up
    notes = _ground(a, "Router AX500 has intermittent connectivity.", "AX-500", "SN10231")
    assert a["serialNumber"]["confidence"] <= 40 and notes


def test_overall_confidence_is_weakest_critical_field():
    a = analyze(EXAMPLE, "AX-500", "SN10231", "UNDER_WARRANTY")
    assert overall_confidence(a) == min(a[f]["confidence"] for f in
                                        ["equipmentModel", "serialNumber", "category", "suspectedCause", "severity", "resolution"])
