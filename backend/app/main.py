"""FastAPI entry point: uvicorn app.main:app --reload"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.errors import register_error_handlers
from app.routes.claims import router as claims_router
from app.schemas import AI_FIELDS, CATEGORIES, DECISION_CRITICAL_FIELDS
from app.seed import seed_registry, seed_sample_claims

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_registry(db)
        if get_settings().seed_sample_claims:
            seed_sample_claims(db)
    yield


settings = get_settings()
app = FastAPI(
    title="AI Service Claim Intelligence & Validation API",
    version="1.0.0",
    description="AI extraction -> confidence -> business validation -> human review -> validated record.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
                   allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type"])
register_error_handlers(app)
app.include_router(claims_router)


@app.get("/api/health", tags=["meta"])
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "postgresql", "aiProvider": settings.ai_provider}


@app.get("/api/config", tags=["meta"])
def public_config():
    """Non-secret settings the UI needs."""
    return {
        "confidenceThreshold": settings.confidence_threshold,
        "aiProvider": settings.ai_provider,
        "categories": CATEGORIES,
        "severities": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
        "aiFields": AI_FIELDS,
        "decisionCriticalFields": DECISION_CRITICAL_FIELDS,
    }
