import os

from dotenv import load_dotenv

load_dotenv()
# Point the app at the TEST database before anything imports app.database
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://claims:claims@localhost:5432/claims_test")
os.environ["AI_PROVIDER"] = "rule_based"
os.environ["UPLOAD_DIR"] = "uploads_test"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:  # runs lifespan -> create_all + seed registry
        yield c


EXAMPLE = {
    "customer": "ABC Manufacturing",
    "equipmentModel": "AX-500",
    "serialNumber": "SN10231",
    "description": "Router AX500 has intermittent connectivity. Customer replaced the power module twice. "
                   "Device is still under warranty. Technician suspects a hardware failure.",
    "serviceDate": "2026-09-20",
    "warrantyStatus": "UNDER_WARRANTY",
}

CLEAN = {
    "customer": "Delta Foods",
    "equipmentModel": "CH-900",
    "serialNumber": "SN77310",
    "description": "Chiller CH-900 serial SN77310 is not cooling since Monday. "
                   "Technician confirmed compressor failure after inspection. Unit is under warranty.",
    "serviceDate": "2026-09-18",
    "warrantyStatus": "UNDER_WARRANTY",
}


@pytest.fixture
def make_claim(client):
    def _make(payload=None, analyze=True):
        r = client.post("/api/claims", json=payload or EXAMPLE)
        assert r.status_code == 201, r.text
        cid = r.json()["claimId"]
        if analyze:
            a = client.post(f"/api/claims/{cid}/analyze")
            assert a.status_code == 200, a.text
            return a.json()
        return r.json()
    return _make
