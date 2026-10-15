# AI Service Claim Intelligence & Validation Platform

Turns free-text service and warranty claims into **structured, reviewable, validated records**.
The AI **predicts**, the business rules **validate**, humans **decide** on anything uncertain,
and only validated data is exported.

```
Claim intake ─► AI prediction ─► Confidence ─► Business validation ─► Final status
  (React form)   (per-field value   (weakest       (rules R1–R6 +        READY_FOR_APPROVAL ─► Approve ─► Export
                  + confidence       critical       warranty registry)   NEEDS_REVIEW ──► Human review ─► Approve / Escalate
                  + evidence)        field)
```

---

## Tech stack (as required by the brief)

| Brief requirement | Choice | Where it lives |
|---|---|---|
| Frontend: React **or** Next.js | **React 18** (Vite) | `frontend/` (`react`, `react-dom`, `react-router-dom` in `package.json`) |
| Backend: Node+Express **or** Python+FastAPI | **Python + FastAPI** | `backend/app/main.py`, `backend/app/routes/claims.py` |
| Database: MongoDB **or** PostgreSQL **or** Supabase | **PostgreSQL 16** (SQLAlchemy 2 + psycopg 3) | `backend/app/models.py`, `docs/schema.sql`, `docker-compose.yml` |
| AI: LLM API / local / mock / rule-based | **Rule-based NLP simulation** (default) **+ optional LLM API** (Anthropic or OpenAI) with automatic fallback | `backend/app/ai/` |
| Testing: Postman, unit, E2E | **Postman** collection, **pytest** (unit + integration), **Vitest**, **Playwright** E2E | `docs/postman/`, `backend/tests/`, `frontend/src/**/*.test.js`, `e2e/` |

---

## Architecture

```
┌───────────────────────── React (Vite) :5173 ─────────────────────────┐
│  Dashboard · Review Queue · New Claim · Claim Detail (review/export) │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ REST/JSON (CORS-restricted)
┌──────────────────────────────▼──────────── FastAPI :8000 ────────────┐
│ routes/claims.py      request validation (Pydantic), state machine    │
│   │                                                                   │
│   ├─► ai/service.py   provider select ─► schema check ─► grounding    │
│   │      ├─ ai/rule_engine.py   (default, deterministic)              │
│   │      └─ ai/llm.py + prompts.py (Anthropic / OpenAI, fallback)     │
│   │                                                                   │
│   ├─► validation.py   R1–R6 routing  ·  approval gate  ·  provenance  │
│   └─► models.py       SQLAlchemy                                      │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────── PostgreSQL :5432 ─────────────┐
│ claims (intake | ai_analysis | validation | final columns)           │
│ claim_events (audit trail)   ·   warranty_registry (system of record) │
└───────────────────────────────────────────────────────────────────────┘
```

### Why the AI never becomes the source of truth

| Layer | Stored in | Can it reach the export? |
|---|---|---|
| AI prediction | `claims.ai_analysis` (value + confidence + evidence per field) | **No.** Only through validation and/or a human decision |
| Validation | `claims.validation` (rule results, flagged fields) | Recorded as `failedRulesAtIntake` |
| Human decisions | `claims.field_reviews` + `claim_events` | Yes, tagged `HUMAN_ACCEPTED / HUMAN_EDITED / HUMAN_REJECTED` |
| Final record | final columns + `claims.final_record` | **Written only on approval** |

Identity fields (model, serial) come from the intake form. Warranty status comes from the **warranty registry**, not from the AI. Every exported field carries a `provenance.source`.

---

## Confidence threshold: **80%** (documented choice)

- Configurable: `CONFIDENCE_THRESHOLD` in `backend/.env`.
- Each of the 9 AI fields has its own confidence, shown in the UI with a threshold marker.
- **Decision-critical fields**: equipmentModel, serialNumber, category, suspectedCause, severity, resolution. Each one must be **≥ 80**, otherwise R2 fails and the claim goes to review.
- **Overall claim confidence = the lowest decision-critical field** (weakest link). A 98% model match does not compensate for a 60% root cause.
- On a claim sent to review, *every* field under 80 must get an explicit Accept/Edit/Reject before approval.

## Business rules

| Rule | Condition | Outcome |
|---|---|---|
| **R1** Missing serial | no serial on intake or in text | Human review |
| **R2** Low AI confidence | any decision-critical field < threshold | Human review |
| **R3** Warranty conflict | claim/AI says UNDER_WARRANTY but the registry says EXPIRED on the service date, or the serial is not in the registry | Human review |
| **R4** High severity | severity = CRITICAL | Human review |
| **R5** Required fields | category/symptom/cause/severity/resolution missing | Human review |
| **R6** Identity mismatch | intake model ≠ model in text, serial mismatch, or registry model ≠ intake model | Human review |
| *Validated* | all pass | **READY_FOR_APPROVAL** (eligible for approval) |

**Approval gate** (enforced server-side): a `NEEDS_REVIEW` claim cannot be approved until every flagged or low-confidence field has a decision **and** a reviewer comment exists. A rejected required field blocks approval; the reviewer must edit it or escalate.

---

## Setup

### Prerequisites
Python 3.11+ (tested on 3.11 and 3.13) · Node 18+ · PostgreSQL 16 (Docker **or** local install)

### 1. Start PostgreSQL
```bash
docker compose up -d          # creates DBs "claims" and "claims_test", user/pass claims/claims
```
<details><summary>Without Docker (macOS Homebrew)</summary>

```bash
brew install postgresql@16 && brew services start postgresql@16
psql postgres -c "CREATE ROLE claims LOGIN PASSWORD 'claims';"
psql postgres -c "CREATE DATABASE claims OWNER claims;" -c "CREATE DATABASE claims_test OWNER claims;"
```
</details>

### 2. Backend (FastAPI)
```bash
cd backend
python3 -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # edit if your DB URL differs
uvicorn app.main:app --reload --port 8000
```
Tables and the warranty registry seed are created on startup. Swagger UI: http://localhost:8000/docs

Optional: load the 8 sample claims:
```bash
python scripts/load_samples.py
```

### 3. Frontend (React)
```bash
cd frontend
npm install
cp .env.example .env                                 # VITE_API_URL=http://localhost:8000
npm run dev                                          # http://localhost:5173
```

### 4. Use a real LLM (optional)
In `backend/.env`:
```
AI_PROVIDER=anthropic          # or openai
ANTHROPIC_API_KEY=sk-ant-...   # or OPENAI_API_KEY=sk-...
```
If the call fails (no key, timeout, bad JSON, schema violation), the rule engine runs instead and the claim shows `aiProvider: "rule_based (fallback)"`.

---

## Deploy to Render

`render.yaml` is a Render Blueprint. It creates three resources:

| Resource | Type | What it does |
|---|---|---|
| `claims-db` | PostgreSQL (free) | Stores claims, the audit trail and the warranty registry |
| `claim-intelligence-api` | Python web service (free) | Runs FastAPI and creates tables on startup |
| `claim-intelligence-web` | Static site | Serves the built React app |

To deploy:

1. In Render, choose **New → Blueprint** and select this repository.
2. Render links the services automatically. The API receives `DATABASE_URL` from the database and accepts requests from the web app's hostname (`CORS_ORIGINS`). The web app receives the API hostname as `VITE_API_URL`.
3. `SEED_SAMPLE_CLAIMS=true` loads the 8 sample claims the first time the API starts with an empty database, so the dashboard has data to show.

Things to know:

- Free web services sleep after about 15 minutes without traffic. The first request after that takes up to a minute.
- Render's free PostgreSQL databases expire after 30 days unless you upgrade them.
- To use a real LLM, set `AI_PROVIDER` to `anthropic` or `openai` and add the matching API key in the Render dashboard. The app falls back to the rule engine if the LLM call fails.

## Tests

```bash
# backend: unit + API integration against the real claims_test PostgreSQL DB
cd backend && pytest -q                         # 42 passed

# frontend unit
cd frontend && npm test                         # 4 passed

# E2E (backend + frontend must be running)
cd e2e && npm install && npx playwright install chromium && npx playwright test   # 5 passed

# Postman: import docs/postman/claim-intelligence.postman_collection.json → Run collection
npx newman run docs/postman/claim-intelligence.postman_collection.json            # 43/43 assertions
```
See [`docs/TEST_CASES.md`](docs/TEST_CASES.md) for the full case list.

---

## Security

- **Input validation**: Pydantic schemas with length limits, enums, no future dates, and markup characters rejected in names. Claim IDs are regex-checked before hitting the DB. All queries go through the SQLAlchemy ORM, so they are parameterised.
- **Uploads**: extension allow-list, size limit, sanitised filename, stored outside the web root, served only via the API.
- **API keys**: read from `.env` only (`.env` is git-ignored, `.env.example` is committed). They are never sent to the frontend; `/api/config` exposes non-secret values only.
- **Errors**: a uniform envelope. The 500 handler never returns stack traces.
- **CORS**: restricted to `CORS_ORIGINS`.
- **Prompt injection**: claim text is wrapped in `<claim>` tags and declared untrusted. The model is told it is not a decision-maker, and its output is schema-validated and grounding-checked.
- React escapes all rendered text; there is no `dangerouslySetInnerHTML`.

---

## Deliverables

| # | Deliverable | Location |
|---|---|---|
| 1 | Source code | `backend/`, `frontend/`, `e2e/` |
| 2 | README | this file |
| 3 | Database schema | [`docs/schema.sql`](docs/schema.sql), `backend/app/models.py` |
| 4 | API documentation | [`docs/API.md`](docs/API.md) + Swagger at `/docs` |
| 5 | Postman collection | [`docs/postman/claim-intelligence.postman_collection.json`](docs/postman/claim-intelligence.postman_collection.json) |
| 6 | AI prompt(s) | [`docs/PROMPTS.md`](docs/PROMPTS.md), `backend/app/ai/prompts.py` |
| 7 | Test cases | [`docs/TEST_CASES.md`](docs/TEST_CASES.md), `backend/tests/`, `e2e/tests/`, `frontend/src/lib/format.test.js` |
| 8 | Screenshots | [`docs/screenshots/`](docs/screenshots) (11 images) |
| 9 | Sample input data | [`docs/samples/sample_claims.json`](docs/samples/sample_claims.json) (8 scenarios) |
| 10 | Sample AI output | [`docs/samples/sample_ai_output.json`](docs/samples/sample_ai_output.json), [`docs/samples/sample_validated_record.json`](docs/samples/sample_validated_record.json) |

## The 5 features

| Feature | Where |
|---|---|
| 1. Service claim intake | `New Claim` page → `POST /api/claims` (JSON or multipart with attachment). Shows Claim ID, timestamp, status |
| 2. AI claim intelligence | `ai/` → model, serial, symptom, cause, part, resolution, severity, warranty, category |
| 3. Confidence & validation engine | per-field confidence bars + threshold marker, 4-stage pipeline view, rules R1–R6 panel |
| 4. Human review & escalation | Accept / Edit / Reject per field, comment, Approve (gated), Escalate (reason required), Review Queue page, audit trail |
| 5. Structured claim output | Validated record in PostgreSQL, JSON view, Download/Copy, `GET /api/claims/:id/export` with provenance |

## Project structure

```
claim-intelligence/
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI app, CORS, lifespan (create tables + seed)
│   │   ├── config.py          env settings
│   │   ├── database.py        engine/session
│   │   ├── models.py          claims, claim_events, warranty_registry
│   │   ├── schemas.py         Pydantic request/response + AI output schema
│   │   ├── errors.py          error envelope
│   │   ├── validation.py      rules R1–R6, approval gate, provenance
│   │   ├── seed.py            warranty registry seed
│   │   ├── routes/claims.py   all /api/claims endpoints
│   │   └── ai/
│   │       ├── service.py     provider selection, fallback, grounding, overall confidence
│   │       ├── rule_engine.py deterministic NLP extraction
│   │       ├── llm.py         Anthropic / OpenAI HTTP clients
│   │       └── prompts.py     system + user prompts
│   ├── tests/                 pytest (unit + integration)
│   ├── scripts/load_samples.py
│   ├── requirements.txt  ·  .env.example  ·  pytest.ini
├── frontend/                  React (Vite)
│   └── src/ App.jsx · pages/{Dashboard,NewClaim,ClaimDetail}.jsx · components/ui.jsx · lib/{api,format}.js
├── e2e/                       Playwright
├── docs/                      API.md · PROMPTS.md · TEST_CASES.md · schema.sql · postman/ · samples/ · screenshots/
└── docker-compose.yml         PostgreSQL 16
```

## Known limitations / next steps
- The rule engine's confidence is heuristic (evidence-strength based). With an LLM, confidences should be calibrated against labelled historical claims.
- No authentication: the reviewer name is free text. Production would add SSO and role-based approve/escalate permissions.
- Analysis runs synchronously in the request. At volume it would move to a queue worker (the `PROCESSING` status already models that).
- Attachments are stored and linked, but not yet fed into the AI (OCR/vision would be the next step).
