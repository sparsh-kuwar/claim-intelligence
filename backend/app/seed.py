"""Seed the warranty registry (the manufacturer's system of record used by Rule R3)
and, optionally, the sample claims used for demo deployments."""
import json
import logging
import pathlib
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Claim, ClaimStatus, WarrantyRecord

SAMPLE_CLAIMS = pathlib.Path(__file__).resolve().parents[2] / "docs" / "samples" / "sample_claims.json"
log = logging.getLogger(__name__)

REGISTRY = [
    # serial,      model,    start,              end
    ("SN10231", "AX-500", date(2025, 1, 15), date(2027, 1, 14)),   # valid
    ("SN10232", "AX-500", date(2022, 3, 1), date(2024, 2, 28)),    # expired -> warranty conflict demo
    ("SN20417", "AX-700", date(2025, 6, 1), date(2028, 5, 31)),
    ("SN55501", "LX-220", date(2025, 2, 10), date(2027, 2, 9)),
    ("SN77310", "CH-900", date(2024, 9, 1), date(2027, 8, 31)),
    ("SN88120", "PX-150", date(2025, 11, 1), date(2027, 10, 31)),
    ("SN90001", "RX-300", date(2023, 1, 1), date(2025, 12, 31)),
]


def seed_registry(db: Session) -> None:
    for serial, model, start, end in REGISTRY:
        if not db.get(WarrantyRecord, serial):
            db.add(WarrantyRecord(serial_number=serial, equipment_model=model, warranty_start=start, warranty_end=end))
    db.commit()


def seed_sample_claims(db: Session) -> int:
    """Submit and analyze each sample claim, exactly as the API would. Skipped if any claim exists."""
    # Imported here so the registry seed does not pull in the API routes.
    from app.routes.claims import _event, analyze_claim
    from app.schemas import ClaimCreate

    if db.scalar(select(func.count(Claim.id))) or not SAMPLE_CLAIMS.exists():
        return 0
    samples = json.loads(SAMPLE_CLAIMS.read_text())
    for data in samples:
        data = {k: v for k, v in data.items() if not k.startswith("_")}
        p = ClaimCreate.model_validate(data)
        claim = Claim(customer=p.customer, equipment_model=p.equipment_model, serial_number=p.serial_number,
                      description=p.description, service_date=p.service_date, warranty_status=p.warranty_status,
                      validation_status=ClaimStatus.PROCESSING, field_reviews={})
        db.add(claim)
        db.flush()
        claim.claim_id = f"CLM-{10000 + claim.id}"
        _event(db, claim, "SUBMITTED", "intake", attachment=None)
        db.commit()
        analyze_claim(claim.claim_id, db)
    log.info("Seeded %d sample claims", len(samples))
    return len(samples)
