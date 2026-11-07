"""Opsoria REST API.

Provides endpoints for incident ingestion, investigation analysis,
health checks, and resolution tracking using FastAPI and Hindsight Cloud memory.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Header, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

import db
import groq_analyst

from hindsight_memory import HindsightMemoryConfig, HindsightMemoryManager
from incident_processor import IncidentProcessor
from models import HistoricalIncidentContext, Incident, IncidentAnalysis

load_dotenv()

logger = logging.getLogger("opsoria.api")


# --- Pydantic Request & Response Schemas ---

class IncidentCreateRequest(BaseModel):
    """Schema for incoming incident ingestion."""

    incident_id: str = Field(..., description="Unique stable incident identifier")
    service: str = Field(..., description="Name of affected service")
    symptoms: str = Field(..., description="Observed symptom or error description")
    environment: str = Field("production", description="Environment (e.g. production, staging)")
    status: str = Field("investigating", description="Incident status")
    possible_causes: list[str] = Field(default_factory=list, description="Unconfirmed hypotheses")
    confirmed_resolution: str | None = Field(None, description="Confirmed resolution if verified")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")

    @field_validator("incident_id", "service", "symptoms")
    @classmethod
    def validate_non_empty(cls, value: str, info) -> str:
        if not value or not value.strip():
            raise ValueError(f"Field '{info.field_name}' must not be empty or whitespace only.")
        return value.strip()


class IncidentResolveRequest(BaseModel):
    """Schema for confirming incident resolution."""

    confirmed_resolution: str = Field(..., description="Confirmed resolution text")

    @field_validator("confirmed_resolution")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Field 'confirmed_resolution' must not be empty or whitespace only.")
        return value.strip()


class HistoricalContextItem(BaseModel):
    """Schema for retrieved historical memory context item."""

    document_id: str
    text: str
    memory_type: str
    scores: dict[str, float | None] | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_synthetic: bool = False


class IncidentAnalysisResponse(BaseModel):
    """Schema for incident investigation analysis response."""

    incident_id: str
    service: str
    environment: str
    status: str
    symptoms: str
    historical_match_count: int
    historical_context: list[HistoricalContextItem]
    investigation_summary: str
    recommended_steps: list[str]
    confirmed_resolution: str | None = None

    # AI Reasoning layer fields (additive, optional)
    ai_label: str = "AI-generated hypotheses - UNVERIFIED. Not a confirmed root cause."
    ai_status: str | None = None
    ai_hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    ai_investigation_plan: list[str] = Field(default_factory=list)
    ai_caveats: list[str] = Field(default_factory=list)

    @classmethod
    def from_analysis(
        cls,
        analysis: IncidentAnalysis,
        ai_result: dict[str, Any] | None = None,
    ) -> IncidentAnalysisResponse:
        context_items = [
            HistoricalContextItem(
                document_id=c.document_id,
                text=c.text,
                memory_type=c.memory_type,
                scores=c.scores,
                tags=c.tags,
                metadata=c.metadata,
                is_synthetic=c.is_synthetic,
            )
            for c in analysis.historical_context
        ]

        ai_status = ai_result.get("ai_status") if ai_result else None
        ai_hypotheses = ai_result.get("ai_hypotheses", []) if ai_result else []
        ai_plan = ai_result.get("ai_investigation_plan", []) if ai_result else []
        ai_caveats = ai_result.get("ai_caveats", []) if ai_result else []

        return cls(
            incident_id=analysis.incident_id,
            service=analysis.service,
            environment=analysis.environment,
            status=analysis.status,
            symptoms=analysis.symptoms,
            historical_match_count=analysis.historical_matches_count,
            historical_context=context_items,
            investigation_summary=analysis.investigation_summary,
            recommended_steps=analysis.recommended_steps,
            confirmed_resolution=analysis.confirmed_resolution,
            ai_status=ai_status,
            ai_hypotheses=ai_hypotheses,
            ai_investigation_plan=ai_plan,
            ai_caveats=ai_caveats,
        )


class HealthResponse(BaseModel):
    """Schema for service health check response."""

    status: str
    hindsight_available: bool
    hindsight_bank_id: str | None
    demo_mode: bool = False


# --- Demo Mode, CORS & Rate Limiting Helpers ---

def get_current_time() -> float:
    """Return current monotonic timestamp (patchable in tests)."""
    return time.monotonic()


def is_demo_mode() -> bool:
    """Return True if DEMO_MODE environment variable is set to a truthy value."""
    return os.getenv("DEMO_MODE", "").strip().lower() in ("1", "true", "yes", "on")


def get_cors_origins() -> list[str]:
    """Return allowed CORS origins from defaults and CORS_ORIGINS env var."""
    origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
    extra = os.getenv("CORS_ORIGINS", "")
    if extra:
        for origin in extra.split(","):
            cleaned = origin.strip()
            if cleaned and cleaned not in origins:
                origins.append(cleaned)
    return origins


def get_client_ip(request: Request) -> str:
    """Extract client IP address, checking X-Forwarded-For first."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",")]
        if parts and parts[0]:
            return parts[0]
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


class DemoRateLimiter:
    """In-memory sliding window rate limiter active when DEMO_MODE is enabled.

    Enforces:
    1. Global sliding 24-hour cap based on DEMO_MAX_ANALYSES_PER_DAY (default 25).
    2. Per-client IP sliding 60-second limit of 3 requests per minute.
    """

    def __init__(self) -> None:
        self._global_timestamps: list[float] = []
        self._ip_timestamps: dict[str, list[float]] = defaultdict(list)

    def reset(self) -> None:
        """Reset all rate limiter state (useful for tests)."""
        self._global_timestamps.clear()
        self._ip_timestamps.clear()

    def get_max_per_day(self) -> int:
        raw = os.getenv("DEMO_MAX_ANALYSES_PER_DAY", "25").strip()
        try:
            val = int(raw)
            return val if val > 0 else 25
        except ValueError:
            return 25

    def check_and_record(self, client_ip: str) -> None:
        """Verify rate limits and record the current request.

        Raises HTTPException(429) if either rate limit is exceeded.
        """
        now = get_current_time()
        max_per_day = self.get_max_per_day()

        # Check global daily cap (sliding 24 hours / 86400s)
        cutoff_day = now - 86400.0
        self._global_timestamps = [t for t in self._global_timestamps if t > cutoff_day]
        if len(self._global_timestamps) >= max_per_day:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Daily demo analysis limit ({max_per_day}) reached. Please try again tomorrow.",
            )

        # Check per-client IP limit (sliding 60s, max 3)
        cutoff_min = now - 60.0
        ip_records = [t for t in self._ip_timestamps[client_ip] if t > cutoff_min]
        self._ip_timestamps[client_ip] = ip_records
        if len(ip_records) >= 3:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demo rate limit reached: maximum 3 analyses per minute per client. Please wait a moment.",
            )

        self._global_timestamps.append(now)
        self._ip_timestamps[client_ip].append(now)


demo_limiter = DemoRateLimiter()


# --- Authentication Dependency ---

def verify_api_key(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
) -> None:
    """Configurable API key verification.

    If OPSORIA_API_KEY environment variable is configured, requests must supply
    a matching Bearer token or X-API-Key header. If unconfigured, requests are allowed.
    """
    configured_key = os.getenv("OPSORIA_API_KEY")
    if not configured_key:
        return  # Auth check disabled when no key is configured

    provided_key = None
    if authorization and authorization.lower().startswith("bearer "):
        provided_key = authorization[7:].strip()
    elif x_api_key:
        provided_key = x_api_key.strip()

    if not provided_key or provided_key != configured_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# --- Application Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage lifecycle of shared Opsoria resources.

    Initializes one HindsightMemoryManager and one IncidentProcessor for the application.
    Releases client connections cleanly during shutdown.
    """
    logger.info("Initializing Opsoria API services...")
    config = HindsightMemoryConfig.from_env()
    memory_manager = HindsightMemoryManager(config=config)
    processor = IncidentProcessor(memory_manager=memory_manager)

    # Initialize SQLite database
    db_path = getattr(app.state, "db_path", db.DEFAULT_DB_PATH)
    db.init_db(db_path=db_path)
    db.seed_demo_if_empty(db_path=db_path)
    app.state.db_path = db_path

    # Attach shared singletons to application state
    app.state.memory_manager = memory_manager
    app.state.processor = processor
    app.state.incident_registry = {}

    logger.info(
        "Opsoria API services initialized. Memory available: %s, DB: %s",
        memory_manager.is_available,
        db_path,
    )

    yield

    logger.info("Shutting down Opsoria API services...")
    if hasattr(app.state, "memory_manager") and app.state.memory_manager:
        app.state.memory_manager.close()
    logger.info("Opsoria API shutdown complete.")


# --- FastAPI Application Factory ---

def create_app() -> FastAPI:
    """Create and configure FastAPI application instance."""
    app = FastAPI(
        title="Opsoria Incident Investigation API",
        description="AI-powered incident investigation assistant with Hindsight Cloud memory.",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse)
    async def health(request: Request):
        """Service health check without executing Retain or Recall."""
        memory_manager: HindsightMemoryManager | None = getattr(
            request.app.state, "memory_manager", None
        )
        is_available = memory_manager.is_available if memory_manager else False
        bank_id = memory_manager.config.bank_id if memory_manager else None

        return HealthResponse(
            status="healthy",
            hindsight_available=is_available,
            hindsight_bank_id=bank_id,
            demo_mode=is_demo_mode(),
        )

    @app.post(
        "/incidents",
        response_model=IncidentAnalysisResponse,
        status_code=status.HTTP_200_OK,
        dependencies=[Depends(verify_api_key)],
    )
    async def ingest_incident_endpoint(
        incident_req: IncidentCreateRequest, request: Request
    ):
        """Ingest an incident, perform historical recall, and synthesize analysis.

        Unresolved incidents are not retained merely upon submission; retention
        occurs only when confirmed resolution rules allow it. Persists to SQLite.
        """
        processor: IncidentProcessor = request.app.state.processor
        db_path = getattr(request.app.state, "db_path", db.DEFAULT_DB_PATH)

        if is_demo_mode():
            if (
                incident_req.confirmed_resolution
                and incident_req.confirmed_resolution.strip()
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Saving resolutions is disabled in the public demo to protect the shared memory bank.",
                )
            demo_limiter.check_and_record(get_client_ip(request))

        incident = Incident(
            incident_id=incident_req.incident_id,
            service=incident_req.service,
            symptoms=incident_req.symptoms,
            environment=incident_req.environment,
            status=incident_req.status,
            possible_causes=incident_req.possible_causes,
            confirmed_resolution=incident_req.confirmed_resolution,
            metadata=incident_req.metadata,
        )

        try:
            analysis = await asyncio.to_thread(processor.process_incident, incident)

            # Generate AI hypotheses via Groq reasoning layer (POST /incidents only)
            ai_result = await asyncio.to_thread(
                groq_analyst.analyze, incident, analysis.historical_context
            )

            # Determine memory_status based on confirmed_resolution and actual retention result
            if incident.confirmed_resolution:
                if (
                    "Resolution confirmed and persisted in Opsoria memory bank."
                    in analysis.recommended_steps
                ):
                    memory_status = "persisted"
                else:
                    memory_status = "not_persisted"
            else:
                memory_status = "not_applicable"

            # Serialize last_analysis with historical_context (including is_synthetic) and AI fields
            analysis_dict = IncidentAnalysisResponse.from_analysis(
                analysis, ai_result=ai_result
            ).model_dump()

            # Persist to SQLite (upsert that never downgrades a resolved incident)
            await asyncio.to_thread(
                db.save_or_upsert_incident,
                incident_id=incident.incident_id,
                service=incident.service,
                environment=incident.environment,
                status=incident.status,
                symptoms=incident.symptoms,
                possible_causes=incident.possible_causes,
                metadata=incident.metadata,
                confirmed_resolution=incident.confirmed_resolution,
                memory_status=memory_status,
                last_analysis=analysis_dict,
                db_path=db_path,
            )

            # Preserve in-memory registry map if present for test backwards compatibility
            if hasattr(request.app.state, "incident_registry"):
                request.app.state.incident_registry[incident.incident_id] = incident

            return IncidentAnalysisResponse.from_analysis(analysis, ai_result=ai_result)
        except Exception as exc:
            logger.error("Unexpected error processing incident %s: %s", incident.incident_id, str(exc))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal error processing incident.",
            )

    @app.post(
        "/incidents/{incident_id}/resolve",
        response_model=IncidentAnalysisResponse,
        status_code=status.HTTP_200_OK,
        dependencies=[Depends(verify_api_key)],
    )
    async def resolve_incident_endpoint(
        incident_id: str,
        resolve_req: IncidentResolveRequest,
        request: Request,
    ):
        """Confirm the resolution of a previously accepted incident.

        Retrieves incident from SQLite, resolves it via IncidentProcessor (which
        triggers Hindsight retention), and updates SQLite with resolution and memory_status.
        """
        processor: IncidentProcessor = request.app.state.processor
        db_path = getattr(request.app.state, "db_path", db.DEFAULT_DB_PATH)

        if is_demo_mode():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Saving resolutions is disabled in the public demo to protect the shared memory bank.",
            )

        stored = await asyncio.to_thread(db.get_incident_by_id, incident_id, db_path)
        if not stored:
            logger.warning("Resolve requested for unknown incident ID: %s", incident_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Incident '{incident_id}' not found in registry.",
            )

        incident = Incident(
            incident_id=stored["incident_id"],
            service=stored["service"],
            environment=stored["environment"],
            status=stored["status"],
            symptoms=stored["symptoms"],
            possible_causes=stored["possible_causes"],
            confirmed_resolution=stored["confirmed_resolution"],
            created_at=stored.get("created_at") or datetime.now(timezone.utc).isoformat(),
            metadata=stored["metadata"],
        )

        try:
            analysis = await asyncio.to_thread(
                processor.resolve_incident, incident, resolve_req.confirmed_resolution
            )

            if (
                "Resolution confirmed and persisted in Opsoria memory bank."
                in analysis.recommended_steps
            ):
                memory_status = "persisted"
            else:
                memory_status = "not_persisted"

            analysis_dict = IncidentAnalysisResponse.from_analysis(analysis).model_dump()

            await asyncio.to_thread(
                db.resolve_incident_in_db,
                incident_id=incident_id,
                confirmed_resolution=resolve_req.confirmed_resolution,
                memory_status=memory_status,
                last_analysis=analysis_dict,
                db_path=db_path,
            )

            return IncidentAnalysisResponse.from_analysis(analysis)
        except Exception as exc:
            logger.error("Unexpected error resolving incident %s: %s", incident_id, str(exc))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal error resolving incident.",
            )

    @app.get(
        "/incidents",
        response_model=list[dict[str, Any]],
        dependencies=[Depends(verify_api_key)],
    )
    async def list_incidents_endpoint(
        request: Request,
        status: str | None = None,
    ):
        """List all incidents ordered newest first, with optional status filter."""
        db_path = getattr(request.app.state, "db_path", db.DEFAULT_DB_PATH)
        return await asyncio.to_thread(db.list_incidents_from_db, status, db_path)

    @app.get(
        "/incidents/{incident_id}",
        response_model=dict[str, Any],
        dependencies=[Depends(verify_api_key)],
    )
    async def get_incident_endpoint(
        incident_id: str,
        request: Request,
    ):
        """Retrieve a full incident record by ID, including its last_analysis."""
        db_path = getattr(request.app.state, "db_path", db.DEFAULT_DB_PATH)
        record = await asyncio.to_thread(db.get_incident_by_id, incident_id, db_path)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Incident '{incident_id}' not found.",
            )
        return record

    @app.get(
        "/stats",
        response_model=dict[str, Any],
        dependencies=[Depends(verify_api_key)],
    )
    async def get_stats_endpoint(request: Request):
        """Get aggregate incident statistics and the 5 most recent incidents."""
        db_path = getattr(request.app.state, "db_path", db.DEFAULT_DB_PATH)
        return await asyncio.to_thread(db.get_incident_stats, db_path)

    return app


app = create_app()

