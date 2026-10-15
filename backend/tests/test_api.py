"""API / integration tests against a real PostgreSQL test database."""
from conftest import CLEAN, EXAMPLE


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["database"] == "postgresql"


def test_create_claim_returns_id_timestamp_status(client):
    r = client.post("/api/claims", json=EXAMPLE)
    assert r.status_code == 201
    body = r.json()
    assert body["claimId"].startswith("CLM-")
    assert body["status"] == "PROCESSING"
    assert body["submittedAt"]


def test_create_claim_multipart_with_attachment(client):
    data = {k: v for k, v in EXAMPLE.items()}
    r = client.post("/api/claims", data=data, files={"attachment": ("photo.png", b"\x89PNG fake", "image/png")})
    assert r.status_code == 201, r.text
    cid = r.json()["claimId"]
    assert client.get(f"/api/claims/{cid}").json()["attachmentName"] == "photo.png"
    assert client.get(f"/api/claims/{cid}/attachment").status_code == 200


def test_rejects_disallowed_attachment(client):
    r = client.post("/api/claims", data=EXAMPLE, files={"attachment": ("evil.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "BAD_ATTACHMENT"


def test_input_validation_errors(client):
    bad = {**EXAMPLE, "customer": "", "description": "short", "serviceDate": "2099-01-01", "warrantyStatus": "MAYBE"}
    r = client.post("/api/claims", json=bad)
    assert r.status_code == 422
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert {"customer", "description", "serviceDate", "warrantyStatus"} <= fields


def test_rejects_markup_in_customer(client):
    r = client.post("/api/claims", json={**EXAMPLE, "customer": "<script>alert(1)</script>"})
    assert r.status_code == 422


def test_unsupported_content_type(client):
    r = client.post("/api/claims", content="x", headers={"Content-Type": "text/plain"})
    assert r.status_code == 415


def test_not_found_and_bad_id(client):
    assert client.get("/api/claims/CLM-99999").status_code == 404
    assert client.get("/api/claims/DROP-TABLE").status_code == 400


def test_analysis_before_analyze_is_409(make_claim, client):
    cid = make_claim(analyze=False)["claimId"]
    assert client.get(f"/api/claims/{cid}/analysis").status_code == 409


def test_low_confidence_routes_to_review(make_claim):
    d = make_claim(EXAMPLE)
    assert d["validationStatus"] == "NEEDS_REVIEW"
    assert "R2" in d["validation"]["failedRules"]
    assert d["category"] is None  # final columns stay empty until approval


def test_clean_claim_is_ready_and_approves_without_review(make_claim, client):
    d = make_claim(CLEAN)
    assert d["validationStatus"] == "READY_FOR_APPROVAL", d["validation"]
    r = client.post(f"/api/claims/{d['claimId']}/approve", json={"reviewer": "auto"})
    assert r.status_code == 200 and r.json()["validationStatus"] == "APPROVED"
    exp = client.get(f"/api/claims/{d['claimId']}/export").json()
    assert exp["approvalPath"] == "AUTO_ELIGIBLE" and exp["category"] == "Hardware Failure"


def test_full_human_review_flow(make_claim, client):
    d = make_claim(EXAMPLE)
    cid = d["claimId"]
    base = f"/api/claims/{cid}"

    # export is refused before validation
    assert client.get(f"{base}/export").status_code == 409

    # approving without review is blocked
    r = client.post(f"{base}/approve", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "APPROVAL_BLOCKED"

    reviews = {f: {"action": "ACCEPT"} for f in d["validation"]["fieldsRequiringReview"]}
    reviews["resolution"] = {"action": "EDIT", "value": "Inspect/replace power module"}
    r = client.patch(f"{base}/review", json={"reviewer": "raj", "fieldReviews": reviews,
                                             "comment": "Technician evidence required."})
    assert r.status_code == 200

    r = client.post(f"{base}/approve", json={"reviewer": "raj"})
    assert r.status_code == 200, r.text
    claim = r.json()
    assert claim["validationStatus"] == "APPROVED"
    assert claim["resolution"] == "Inspect/replace power module"   # human value, not AI value

    exp = client.get(f"{base}/export").json()
    assert exp["resolution"] == "Inspect/replace power module"
    assert exp["provenance"]["resolution"]["source"] == "HUMAN_EDITED"
    assert exp["approvalPath"] == "HUMAN_REVIEW"
    assert "resolution" in exp["humanVerifiedFields"]
    events = [e["eventType"] for e in client.get(base).json()["events"]]
    assert events == ["SUBMITTED", "AI_ANALYZED", "VALIDATED", "REVIEWED", "APPROVED"]


def test_review_validates_field_names_and_values(make_claim, client):
    cid = make_claim(EXAMPLE)["claimId"]
    r = client.patch(f"/api/claims/{cid}/review", json={"fieldReviews": {"notAField": {"action": "ACCEPT"}}})
    assert r.status_code == 422
    r = client.patch(f"/api/claims/{cid}/review", json={"fieldReviews": {"severity": {"action": "EDIT", "value": "HUGE"}}})
    assert r.status_code == 422
    r = client.patch(f"/api/claims/{cid}/review", json={"fieldReviews": {"symptom": {"action": "EDIT"}}})
    assert r.status_code == 422


def test_escalate_then_state_is_locked(make_claim, client):
    cid = make_claim(EXAMPLE)["claimId"]
    assert client.post(f"/api/claims/{cid}/escalate", json={"reason": ""}).status_code == 422
    r = client.post(f"/api/claims/{cid}/escalate", json={"reviewer": "raj", "reason": "Needs engineering RCA"})
    assert r.status_code == 200 and r.json()["validationStatus"] == "ESCALATED"
    assert client.post(f"/api/claims/{cid}/approve", json={}).status_code == 409
    assert client.get(f"/api/claims/{cid}/export").status_code == 409


def test_warranty_conflict_via_registry(make_claim):
    d = make_claim({**CLEAN, "serialNumber": "SN10232", "equipmentModel": "AX-500",
                    "description": "Router AX-500 does not power on. Technician confirmed power module failure."})
    assert "R3" in d["validation"]["failedRules"]
    assert d["validation"]["registryWarrantyStatus"] == "EXPIRED"


def test_list_filter_and_counts(make_claim, client):
    make_claim(EXAMPLE)
    r = client.get("/api/claims", params={"status": "NEEDS_REVIEW"})
    body = r.json()
    assert r.status_code == 200 and body["total"] >= 1
    assert all(i["validationStatus"] == "NEEDS_REVIEW" for i in body["items"])
    assert set(body["counts"]) == {"PROCESSING", "NEEDS_REVIEW", "READY_FOR_APPROVAL", "APPROVED", "ESCALATED"}
    assert client.get("/api/claims", params={"status": "BOGUS"}).status_code == 400


def test_llm_failure_falls_back_to_rule_engine(make_claim, client, monkeypatch):
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "ai_provider", "anthropic")
    monkeypatch.setattr(s, "anthropic_api_key", "")  # no key -> LLMError -> fallback
    d = make_claim(EXAMPLE)
    assert d["aiProvider"] == "rule_based (fallback)"
    assert d["validation"]["aiMeta"]["fallbackReason"]


def test_llm_output_is_schema_checked_and_grounded(make_claim, monkeypatch):
    """Simulate an LLM response: valid shape, but a hallucinated serial and an off-list category."""
    from app.ai import service
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "ai_provider", "openai")

    def fake_llm(settings, **claim):
        f = lambda v, c: {"value": v, "confidence": c, "evidence": None}
        return {"equipmentModel": f("AX500", 97), "serialNumber": f("SN00000", 95), "category": f("Gremlins", 90),
                "symptom": f("Intermittent connectivity", 92), "suspectedCause": f("Power module failure", 70),
                "affectedPart": f("Power Module", 80), "severity": f("high", 85),
                "resolution": f("Replace power module", 75), "warrantyRelevance": f("UNDER_WARRANTY", 90)}

    monkeypatch.setattr(service, "call_openai", fake_llm)
    d = make_claim(EXAMPLE)
    a = d["aiAnalysis"]
    assert d["aiProvider"] == "openai"
    assert a["equipmentModel"]["value"] == "AX-500"           # normalised
    assert a["serialNumber"]["confidence"] <= 40               # not in text or intake -> capped
    assert a["category"]["value"] == "Other" and a["category"]["confidence"] <= 50
    assert a["severity"]["value"] == "HIGH"
    assert d["validationStatus"] == "NEEDS_REVIEW"
