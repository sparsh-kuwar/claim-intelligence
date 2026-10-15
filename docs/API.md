# API Documentation

Base URL: `http://localhost:8000` · Interactive docs (Swagger): **`/docs`** · OpenAPI JSON: `/openapi.json`
Postman: [`postman/claim-intelligence.postman_collection.json`](postman/claim-intelligence.postman_collection.json) (24 requests, 43 assertions)

All JSON uses camelCase. Every error uses one envelope:

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "Claim validation failed",
             "details": [{ "field": "serialNumber", "message": "..." }] } }
```

| Code | HTTP | When |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Body/field validation failed |
| `BAD_ATTACHMENT` / `ATTACHMENT_TOO_LARGE` | 422 / 413 | File type not allowed / over `MAX_UPLOAD_MB` |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | Not JSON or multipart |
| `BAD_CLAIM_ID` | 400 | ID not in `CLM-nnnnn` form |
| `NOT_FOUND` | 404 | Unknown claim |
| `INVALID_STATE` | 409 | Action not allowed in the current status (e.g. approve an escalated claim) |
| `NOT_ANALYZED` | 409 | `/analysis` requested before `/analyze` |
| `APPROVAL_BLOCKED` | 422 | Approve attempted while flagged fields are undecided, no comment, or a required field was rejected |
| `NOT_VALIDATED` | 409 | Export requested for a non-approved claim |
| `INTERNAL_ERROR` | 500 | Unhandled. No stack trace is returned |

## Status lifecycle

```
POST /claims ─► PROCESSING ─► POST /analyze ─┬─► READY_FOR_APPROVAL ─┬─► APPROVED  (export allowed)
                                             │                       └─► ESCALATED
                                             └─► NEEDS_REVIEW ───────┬─► APPROVED  (needs decisions + comment)
                                                                     └─► ESCALATED (needs reason)
```

---

## Endpoints

### `POST /api/claims`: submit a claim
Accepts `application/json` **or** `multipart/form-data` (same fields plus an optional `attachment` file: pdf/png/jpg/txt/log/csv, ≤ 5 MB).

| Field | Type | Rules |
|---|---|---|
| `customer` | string | 2–200 chars, no markup characters |
| `equipmentModel` | string | 1–100 chars |
| `serialNumber` | string? | optional (missing serial triggers R1) |
| `description` | string | 10–5000 chars |
| `serviceDate` | date `YYYY-MM-DD` | not in the future |
| `warrantyStatus` | enum | `UNDER_WARRANTY` · `EXPIRED` · `UNKNOWN` |

```bash
curl -X POST localhost:8000/api/claims -H 'Content-Type: application/json' -d '{
  "customer":"ABC Manufacturing","equipmentModel":"AX-500","serialNumber":"SN10231",
  "description":"Router AX500 has intermittent connectivity. Customer replaced the power module twice. Device is still under warranty. Technician suspects a hardware failure.",
  "serviceDate":"2026-09-20","warrantyStatus":"UNDER_WARRANTY"}'
```
`201`
```json
{ "claimId": "CLM-10001", "customer": "ABC Manufacturing", "equipmentModel": "AX-500",
  "serialNumber": "SN10231", "status": "PROCESSING", "submittedAt": "2026-09-24T18:30:01.255392+00:00" }
```

### `GET /api/claims`: list
Query: `status` (one of the 5 statuses), `search` (ID/customer/model/serial), `limit` (1–200, default 50), `offset`.
Returns `{ items: [...summary], total, counts: {PROCESSING, NEEDS_REVIEW, READY_FOR_APPROVAL, APPROVED, ESCALATED} }`.

### `GET /api/claims/:id`: full claim
Intake, `aiAnalysis`, `validation`, `fieldReviews`, final columns (null until approved), `validationStatus` and `events` (audit trail).

### `GET /api/claims/:id/attachment`: download the attachment

### `POST /api/claims/:id/analyze`: AI + business validation
Runs the AI provider, the grounding checks and rules R1–R6, then sets status to `READY_FOR_APPROVAL` or `NEEDS_REVIEW`.
You can re-run it while the claim is not in a final state. Re-running clears earlier field reviews.

Response (abridged):
```json
{
  "claimId": "CLM-10001",
  "validationStatus": "NEEDS_REVIEW",
  "aiProvider": "rule_based",
  "aiConfidence": 55,
  "aiAnalysis": {
    "category":       { "value": "Hardware Failure", "confidence": 91, "evidence": "technician statement says hardware failure" },
    "suspectedCause": { "value": "Power Module failure", "confidence": 60, "evidence": "...already replaced (twice) and issue persists" },
    "...": "9 fields total"
  },
  "validation": {
    "threshold": 80,
    "outcome": "NEEDS_REVIEW",
    "failedRules": ["R2"],
    "flaggedFields": ["suspectedCause", "resolution"],
    "fieldsRequiringReview": ["suspectedCause", "affectedPart", "resolution"],
    "registryWarrantyStatus": "UNDER_WARRANTY",
    "rules": [ { "id": "R2", "name": "AI confidence >= 80%", "passed": false,
                 "message": "Low confidence: suspectedCause 60%, resolution 55%", "fields": ["suspectedCause","resolution"] } ]
  },
  "category": null, "severity": null, "confidence": null
}
```

### `GET /api/claims/:id/analysis`: AI output and validation only

### `PATCH /api/claims/:id/review`: per-field human decisions
```json
{
  "reviewer": "analyst",
  "fieldReviews": {
    "suspectedCause": { "action": "ACCEPT" },
    "resolution":     { "action": "EDIT", "value": "Inspect/replace power module" },
    "affectedPart":   { "action": "REJECT" }
  },
  "comment": "Technician evidence required."
}
```
`action` ∈ `ACCEPT | EDIT | REJECT`. `EDIT` requires a value. `severity` and `category` edits must use a valid label. Unknown field names return 422. Calls merge, so you can send one field at a time.

### `POST /api/claims/:id/approve`
Body: `{ "reviewer": "analyst", "comment": "optional" }`.
Builds the validated record and writes the final columns plus `final_record`.
**Blocked (422 `APPROVAL_BLOCKED`)** in any of these cases:
- The claim is `NEEDS_REVIEW` and a field in `fieldsRequiringReview` has no decision.
- The claim is `NEEDS_REVIEW` and there is no reviewer comment.
- A required field (category, symptom, suspectedCause, severity, resolution) was rejected or is empty. Edit it or escalate.
- There is no serial number.

### `POST /api/claims/:id/escalate`
Body: `{ "reviewer": "analyst", "reason": "Needs engineering RCA" }`. `reason` is required.

### `GET /api/claims/:id/export`: validated record
`?download=true` adds `Content-Disposition: attachment`. Returns 409 unless the claim is `APPROVED`.
Example: [`samples/sample_validated_record.json`](samples/sample_validated_record.json)

```json
{
  "claimId": "CLM-10001", "customer": "ABC Manufacturing", "equipmentModel": "AX-500", "serialNumber": "SN10231",
  "serviceDate": "2026-09-20", "warrantyStatus": "UNDER_WARRANTY",
  "category": "Hardware Failure", "symptom": "Intermittent connectivity",
  "suspectedCause": "Power Module failure", "affectedPart": "Power Module", "severity": "HIGH",
  "resolution": "Inspect/replace power module", "confidence": 55, "status": "APPROVED",
  "approvalPath": "HUMAN_REVIEW",
  "humanVerifiedFields": ["suspectedCause", "affectedPart", "resolution"],
  "failedRulesAtIntake": ["R2"],
  "provenance": { "resolution": { "source": "HUMAN_EDITED", "aiConfidence": 55 }, "...": "..." },
  "reviewer": "analyst", "reviewerComment": "Technician evidence required.",
  "aiProvider": "rule_based", "approvedAt": "2026-09-24T18:30:08+00:00"
}
```
`confidence` is the AI's original overall confidence, reported honestly. Human verification shows up in `provenance`/`humanVerifiedFields`; the score is not inflated to 100.

### Meta
- `GET /api/health`: `{status, database, aiProvider}` (performs `SELECT 1`)
- `GET /api/config`: threshold, provider, category and severity lists for the UI. Contains no secrets.
