# Test Cases

| Layer | Tool | Location | Count | Command |
|---|---|---|---|---|
| AI extraction (unit) | pytest | `backend/tests/test_rule_engine.py` | 12 | `cd backend && pytest tests/test_rule_engine.py` |
| Business rules (unit) | pytest | `backend/tests/test_validation.py` | 12 | `pytest tests/test_validation.py` |
| API + DB (integration, real PostgreSQL) | pytest + TestClient | `backend/tests/test_api.py` | 18 | `pytest tests/test_api.py` |
| UI logic (unit) | Vitest | `frontend/src/lib/format.test.js` | 4 | `cd frontend && npm test` |
| End-to-end (browser) | Playwright | `e2e/tests/claim-flow.spec.js` | 5 | `cd e2e && npx playwright test` |
| API contract | Postman / Newman | `docs/postman/*.json` | 24 req / 43 assertions | Collection Runner or `npx newman run ...` |

Last run: **42 pytest passed · 4 vitest passed · 5 Playwright passed · 43/43 Postman assertions passed.**

## Key cases (what each proves)

| ID | Case | Expected | Covered by |
|---|---|---|---|
| TC-01 | Submit valid claim | 201, `CLM-nnnnn`, timestamp, `PROCESSING` | api, postman, e2e |
| TC-02 | Submit with attachment (multipart) | stored, downloadable | api |
| TC-03 | Disallowed attachment `.exe` | 422 `BAD_ATTACHMENT` | api |
| TC-04 | Empty customer / short description / future date / bad enum | 422 with every field listed | api, postman, e2e (client-side) |
| TC-05 | `<script>` in customer name | 422 | api |
| TC-06 | PDF example claim extraction | AX-500, SN10231, Hardware Failure, Intermittent connectivity, Power Module, HIGH | rule_engine |
| TC-07 | Part replaced twice and issue persists | root-cause confidence < 80 with evidence note | rule_engine |
| TC-08 | "still under warranty" | not misread as "issue still persists" | rule_engine |
| TC-09 | "out of warranty" | EXPIRED (negation handled) | rule_engine |
| TC-10 | No serial anywhere | `null`, confidence 0 (not invented) | rule_engine |
| TC-11 | LLM returns a serial not present in the input | confidence capped at 40 (grounding) | rule_engine |
| TC-12 | Overall confidence | = weakest decision-critical field | rule_engine |
| TC-13 | R1 missing serial | NEEDS_REVIEW, serialNumber flagged | validation, api |
| TC-14 | R2 confidence < threshold | NEEDS_REVIEW; threshold configurable | validation, api, postman |
| TC-15 | R3 claim says under warranty, registry says expired | NEEDS_REVIEW | validation, api |
| TC-16 | R3 serial not in registry | NEEDS_REVIEW (cannot verify) | validation |
| TC-17 | R4 CRITICAL severity | NEEDS_REVIEW | validation, postman, e2e |
| TC-18 | R5 missing required field | NEEDS_REVIEW | validation |
| TC-19 | R6 intake model ≠ description model | NEEDS_REVIEW | validation |
| TC-20 | Clean claim | READY_FOR_APPROVAL, approve without edits, `approvalPath=AUTO_ELIGIBLE` | validation, api, postman, e2e |
| TC-21 | Approve NEEDS_REVIEW claim with undecided fields | 422 `APPROVAL_BLOCKED` | api, postman, e2e |
| TC-22 | Approve NEEDS_REVIEW claim without comment | 422 | validation |
| TC-23 | Reject a required field then approve | 422 (must edit or escalate) | validation |
| TC-24 | Accept / edit / reject, comment, approve | APPROVED; edited value used, not the AI value | api, postman, e2e |
| TC-25 | Export before approval | 409 `NOT_VALIDATED` | api, postman |
| TC-26 | Export after approval | provenance shows `HUMAN_EDITED`, `humanVerifiedFields` listed | api, postman, e2e |
| TC-27 | Escalate without reason | 422 | api, postman, e2e |
| TC-28 | Approve after escalation | 409 `INVALID_STATE` | api |
| TC-29 | Review with unknown field / invalid severity / EDIT without value | 422 | api |
| TC-30 | LLM provider fails (no key) | falls back to rule engine, `aiProvider="rule_based (fallback)"` | api |
| TC-31 | Audit trail | SUBMITTED → AI_ANALYZED → VALIDATED → REVIEWED → APPROVED | api, e2e |
| TC-32 | Review queue filter | only NEEDS_REVIEW rows | api, e2e |
| TC-33 | Unknown ID / malformed ID | 404 / 400 | api, postman |
| TC-34 | LLM output with hallucinated serial + off-list category | serial capped ≤40, category → Other, severity normalised | api |
