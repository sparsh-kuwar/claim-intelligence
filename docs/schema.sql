-- =====================================================================
-- AI Service Claim Intelligence — PostgreSQL schema
-- Equivalent to what SQLAlchemy creates on API startup (app/models.py).
-- Apply manually with:  psql "$DATABASE_URL" -f docs/schema.sql
-- =====================================================================

-- ---------------------------------------------------------------------
-- claims: one row per service/warranty claim
--   intake columns      -> what the submitter said
--   ai_* / validation   -> AI prediction + rule results (NOT source of truth)
--   final columns       -> written ONLY on approval, from validated values
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS claims (
    id                  SERIAL PRIMARY KEY,
    claim_id            VARCHAR(20) UNIQUE,              -- CLM-10001 (derived from id)

    -- intake
    customer            VARCHAR(200) NOT NULL,
    equipment_model     VARCHAR(100) NOT NULL,
    serial_number       VARCHAR(100),                    -- nullable: missing serial -> rule R1
    description         TEXT         NOT NULL,
    service_date        DATE         NOT NULL,
    warranty_status     VARCHAR(20)  NOT NULL,           -- UNDER_WARRANTY | EXPIRED | UNKNOWN (as claimed)
    attachment_name     VARCHAR(255),
    attachment_path     VARCHAR(500),

    -- AI layer (prediction)
    ai_analysis         JSONB,        -- {field: {value, confidence, evidence}} x 9 fields
    ai_provider         VARCHAR(50),  -- rule_based | anthropic | openai | "rule_based (fallback)"
    ai_confidence       INTEGER,      -- weakest decision-critical field (0-100)

    -- validation layer
    validation          JSONB,        -- {threshold, rules[], outcome, failedRules, flaggedFields, ...}
    field_reviews       JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {field: {action, value, reviewer, at}}

    -- final validated record (populated on approval only)
    category            VARCHAR(100),
    symptom             TEXT,
    suspected_cause     TEXT,
    affected_part       VARCHAR(200),
    severity            VARCHAR(20),
    resolution          TEXT,
    confidence          INTEGER,
    final_record        JSON,         -- exact export payload (JSON keeps key order)

    validation_status   VARCHAR(30) NOT NULL DEFAULT 'PROCESSING',
        -- PROCESSING | NEEDS_REVIEW | READY_FOR_APPROVAL | APPROVED | ESCALATED
    reviewer_comment    TEXT,
    reviewed_by         VARCHAR(100),

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_claims_claim_id          ON claims (claim_id);
CREATE INDEX IF NOT EXISTS ix_claims_validation_status ON claims (validation_status);

-- ---------------------------------------------------------------------
-- claim_events: append-only audit trail
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS claim_events (
    id          SERIAL PRIMARY KEY,
    claim_pk    INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    event_type  VARCHAR(50)  NOT NULL,   -- SUBMITTED | AI_ANALYZED | VALIDATED | REVIEWED | APPROVED | ESCALATED
    actor       VARCHAR(100) NOT NULL,   -- intake | ai:<provider> | rule-engine | <reviewer>
    details     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_claim_events_claim_pk ON claim_events (claim_pk);

-- ---------------------------------------------------------------------
-- warranty_registry: manufacturer system of record (used by rule R3)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS warranty_registry (
    serial_number    VARCHAR(100) PRIMARY KEY,
    equipment_model  VARCHAR(100) NOT NULL,
    warranty_start   DATE NOT NULL,
    warranty_end     DATE NOT NULL
);

INSERT INTO warranty_registry (serial_number, equipment_model, warranty_start, warranty_end) VALUES
    ('SN10231', 'AX-500', '2025-01-15', '2027-01-14'),
    ('SN10232', 'AX-500', '2022-03-01', '2024-02-28'),   -- expired: warranty-conflict demo
    ('SN20417', 'AX-700', '2025-06-01', '2028-05-31'),
    ('SN55501', 'LX-220', '2025-02-10', '2027-02-09'),
    ('SN77310', 'CH-900', '2024-09-01', '2027-08-31'),
    ('SN88120', 'PX-150', '2025-11-01', '2027-10-31'),
    ('SN90001', 'RX-300', '2023-01-01', '2025-12-31')
ON CONFLICT (serial_number) DO NOTHING;
