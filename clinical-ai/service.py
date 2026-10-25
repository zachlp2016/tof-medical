"""Internal bearer-authenticated HTTP adapter. No request/output persistence or logging."""
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

# Enforce offline loading even when an operator forgets the deployment flags.
for name in ("OPENMED_OFFLINE", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
    os.environ[name] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["DO_NOT_TRACK"] = "1"

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware
from artifacts import read_lock
from engine import Engine, WorkerBusy

# Inference errors can include tensor or source snippets upstream. Never forward
# their exception strings/tracebacks to logs, metrics, responses, or audit.
logging.disable(logging.CRITICAL)
MAX_BODY_BYTES = 128 * 1024


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=20000)
    operation: Literal["deidentify", "entities"]


@asynccontextmanager
async def lifespan(app):
    app.state.engine = None
    app.state.token = None
    try:
        token_file = Path(os.environ["AI_SERVICE_TOKEN_FILE"])
        token = token_file.read_text(encoding="utf-8").strip()
        if len(token) < 32 or len(token) > 512 or not token.isascii():
            raise ValueError("Invalid service credential")
        app.state.token = token
        app.state.engine = Engine(Path(os.environ.get("MODEL_ROOT", "/models")))
    except Exception:
        # Keep health available; readiness explicitly fails without good assets.
        app.state.engine = None
    yield
    app.state.engine = None
    app.state.token = None


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
allowed_hosts = [host.strip() for host in os.environ.get(
    "OPENMED_ALLOWED_HOSTS", "openmed,localhost,127.0.0.1,testserver"
).split(",") if host.strip()]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)


def error(status: int, code: str):
    return JSONResponse(status_code=status, content={"error": code}, headers={"Cache-Control": "no-store"})


def metadata():
    lock = read_lock()
    ready = app.state.engine is not None
    return {"status": "ok" if ready else "unavailable", "ready": ready,
            "artifactsVerified": ready, "sdkVersion": lock["sdkVersion"],
            "models": {operation: {key: model[key] for key in ("id", "revision")}
                       for operation, model in lock["models"].items()}}


@app.get("/healthz")
async def health():
    return JSONResponse(metadata(), headers={"Cache-Control": "no-store"})


@app.get("/readyz")
async def ready():
    payload = metadata()
    return JSONResponse(payload, status_code=200 if payload["ready"] else 503,
                        headers={"Cache-Control": "no-store"})


@app.post("/review")
async def review(request: Request):
    if request.headers.get("origin"):
        return error(403, "origin_denied")
    token = request.app.state.token
    header = request.headers.get("authorization", "")
    if not token or not hmac.compare_digest(header.encode("utf-8"), ("Bearer " + token).encode("ascii")):
        return error(401, "unauthorized")
    if request.app.state.engine is None:
        return error(503, "models_unavailable")
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        return error(415, "json_required")
    try:
        if int(request.headers.get("content-length", "0")) > MAX_BODY_BYTES:
            return error(413, "input_too_large")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY_BYTES:
                return error(413, "input_too_large")
        payload = ReviewRequest.model_validate(json.loads(body))
        if not payload.text.strip():
            return error(422, "invalid_input")
    except (ValueError, ValidationError, UnicodeError):
        return error(422, "invalid_input")
    try:
        result = await run_in_threadpool(request.app.state.engine.review, payload.text, payload.operation)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    except WorkerBusy:
        return error(429, "worker_busy")
    except TimeoutError:
        return error(504, "inference_timeout")
    except Exception:
        return error(503, "inference_unavailable")
