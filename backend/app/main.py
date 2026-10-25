from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from sqlalchemy import text
from .auth import AuthMiddleware
from .config import Settings
from .db import Base, Database
from .models import SchemaVersion
from .clinical_ai import ClinicalAIClient, ClinicalAIError
from .mcp_server import create_mcp, TOOL_DESCRIPTIONS
from .schemas import PatientCreate, AppointmentCreate, AppointmentStatus, EncounterCreate, NoteUpdate, TaskStatus, ClinicalReviewRequest, ClinicalAIVerifyRequest
from .seed import seed_demo
from .service import EHRService


def create_app(settings=None):
    settings = settings or Settings.from_env()
    database = Database(settings.database_url)
    credentials = {}
    clinical_ai = ClinicalAIClient(settings)
    mcp = create_mcp(database, settings)
    mcp_http = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        credentials.update(settings.load_principals())
        if settings.demo_mode:
            Base.metadata.create_all(database.engine)
            with database.session() as session:
                if session.get(SchemaVersion, 1) is None:
                    session.add(SchemaVersion(version=1))
            seed_demo(database)
        else:
            with database.session() as session:
                if session.get(SchemaVersion, 1) is None:
                    raise RuntimeError("Database schema is not initialized; run python -m migrations.001_initial first")
        async with mcp.session_manager.run():
            yield
        database.engine.dispose()

    app = FastAPI(title="TOF Clinical EHR", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/docs" if settings.demo_mode else None,
                  openapi_url="/api/openapi.json" if settings.demo_mode else None,
                  redoc_url=None)
    app.state.database, app.state.settings, app.state.mcp = database, settings, mcp
    app.state.clinical_ai = clinical_ai
    app.add_middleware(AuthMiddleware, settings=settings, credentials=credentials)

    def service(request):
        return EHRService(database, request.state.principal)

    @app.middleware("http")
    async def secure_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith(("/api/", "/mcp")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    def health():
        return {"status": "ok", "service": "tof-ehr"}

    @app.get("/readyz")
    def ready():
        try:
            with database.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return {"status": "ready"}
        except Exception:
            return JSONResponse({"status": "not-ready"}, status_code=503)

    @app.get("/api/dashboard")
    def dashboard(request: Request):
        return service(request).dashboard()

    @app.get("/api/patients")
    def patients(request: Request, search: str = Query(default="", max_length=100)):
        return service(request).patients(search)

    @app.post("/api/patients", status_code=201)
    def create_patient(data: PatientCreate, request: Request):
        return service(request).create_patient(data)

    @app.get("/api/patients/{patient_id}")
    def chart(patient_id: str, request: Request):
        return service(request).patient_chart(patient_id)

    @app.get("/api/appointments")
    def appointments(request: Request, date: date | None = None, patientId: str | None = Query(default=None, max_length=36)):
        return service(request).appointments(date, patientId)

    @app.post("/api/appointments", status_code=201)
    def create_appointment(data: AppointmentCreate, request: Request):
        return service(request).create_appointment(data)

    @app.patch("/api/appointments/{appointment_id}")
    def update_appointment(appointment_id: str, data: AppointmentStatus, request: Request):
        return service(request).update_appointment(appointment_id, data.status)

    @app.get("/api/encounters")
    def encounters(request: Request, patientId: str | None = Query(default=None, max_length=36)):
        return service(request).encounters(patientId)

    @app.post("/api/encounters", status_code=201)
    def create_encounter(data: EncounterCreate, request: Request):
        return service(request).create_encounter(data)

    @app.get("/api/encounters/{encounter_id}")
    def encounter(encounter_id: str, request: Request):
        return service(request).encounter(encounter_id)

    @app.patch("/api/encounters/{encounter_id}/note")
    def update_note(encounter_id: str, data: NoteUpdate, request: Request):
        return service(request).update_note(encounter_id, data)

    @app.get("/api/encounters/{encounter_id}/history")
    def note_history(encounter_id: str, request: Request):
        return service(request).note_history(encounter_id)

    @app.post("/api/encounters/{encounter_id}/review")
    async def clinical_review(encounter_id: str, data: ClinicalReviewRequest, request: Request):
        svc = service(request)
        snapshot = await run_in_threadpool(svc.clinical_review_snapshot, encounter_id, data.expectedVersion, data.operation)
        try:
            result = await app.state.clinical_ai.review(snapshot["text"], data.operation)
        except ClinicalAIError as exc:
            await run_in_threadpool(svc.clinical_review_audit, encounter_id, data.operation, failure=exc.category)
            raise HTTPException(exc.status_code, exc.public_message,
                                headers={"Retry-After": "5"} if exc.status_code == 429 else None) from None
        await run_in_threadpool(svc.verify_clinical_review_version, encounter_id, snapshot["encounterVersion"], data.operation)
        await run_in_threadpool(svc.clinical_review_audit, encounter_id, data.operation, model=result["model"])
        return {"encounterId": snapshot["encounterId"], "encounterVersion": snapshot["encounterVersion"], **result}

    @app.get("/api/ai/status")
    async def clinical_ai_status(request: Request):
        await run_in_threadpool(service(request).require, "ehr:read")
        return await app.state.clinical_ai.status()

    @app.post("/api/ai/verify")
    async def clinical_ai_verify(request: Request, data: ClinicalAIVerifyRequest | None = None):
        svc = service(request)
        await run_in_threadpool(svc.require, "ehr:write")
        await run_in_threadpool(svc.clinical_ai_verification_audit, "requested")
        try:
            result = await app.state.clinical_ai.verify()
        except ClinicalAIError as exc:
            await run_in_threadpool(svc.clinical_ai_verification_audit, "failed")
            raise HTTPException(exc.status_code, exc.public_message,
                                headers={"Retry-After": "5"} if exc.status_code == 429 else None) from None
        await run_in_threadpool(svc.clinical_ai_verification_audit, "completed")
        return result

    @app.get("/api/tasks")
    def tasks(request: Request):
        return service(request).tasks()

    @app.patch("/api/tasks/{task_id}")
    def update_task(task_id: str, data: TaskStatus, request: Request):
        return service(request).update_task(task_id, data.status)

    @app.get("/api/audit")
    def audit(request: Request):
        return service(request).audit_events()

    @app.get("/api/integration")
    def integration(request: Request):
        svc = service(request)
        svc.require("ehr:read")
        p = request.state.principal
        return {"service": "TOF Clinical EHR", "status": "ready", "mode": "demo" if settings.demo_mode else "production",
                "mcpEndpoint": "/mcp", "protocolVersion": "2025-11-25", "tools": [{"name": name, "description": description} for name, description in TOOL_DESCRIPTIONS.items()],
                "tenantId": p.tenant_id, "actorId": p.actor_id, "scopes": sorted(p.scopes),
                "syntheticData": settings.demo_mode, "connectedToTof": False,
                "clinicalAi": {"configured": clinical_ai.configured, "statusEndpoint": "/api/ai/status", "reviewRequired": True}}

    # Copy the official SDK routes directly to preserve exact /mcp (no slash redirect).
    app.router.routes.extend(mcp_http.routes)

    frontend = Path(settings.frontend_dir)
    if (frontend / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend_page(path: str):
        if path.startswith(("api/", "mcp/")):
            raise HTTPException(404, "Not found")
        requested = (frontend / path).resolve()
        if requested.is_relative_to(frontend.resolve()) and requested.is_file():
            return FileResponse(requested)
        if (frontend / "index.html").is_file():
            return FileResponse(frontend / "index.html")
        return {"service": "TOF Clinical EHR", "frontend": "not-built", "health": "/healthz"}

    return app


app = create_app()
