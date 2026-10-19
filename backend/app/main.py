"""OEMS API — FastAPI application factory.

Run:  uvicorn app.main:app --reload --port 8000   (from the backend/ folder)
Docs: http://localhost:8000/docs
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routers import attempts, auth, db_meta, exams, questions, results, sql_lab, system, users
from app.core.config import get_settings
from app.core.context import request_id_var
from app.core.errors import error_body, install_error_handlers
from app.core.logging import configure_logging
from app.core.metrics import metrics
from app.db.engines import dispose_all

log = logging.getLogger("oems.http")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    log.info("OEMS API starting", extra={"database": settings.db_name, "lab_database": settings.lab_db_name,
                                         "freeform_sql": settings.sql_freeform_enabled})
    yield
    dispose_all()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="OEMS API", version="1.0.0", lifespan=lifespan,
                  description="Online Examination Management System with an interactive DBMS lab.")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-ID"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        """Correlation id, request-size limit, structured access log and latency metrics."""
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if incoming.replace("-", "").isalnum() and len(incoming) <= 64 else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > settings.max_request_bytes:
                response = JSONResponse(error_body("payload_too_large",
                                                   f"Request body limit is {settings.max_request_bytes} bytes."),
                                        status_code=413)
            else:
                try:
                    response = await call_next(request)
                except Exception:  # noqa: BLE001 - last line of defence, keeps the request id + metrics
                    log.exception("unhandled error")
                    response = JSONResponse(error_body("internal_error", "An unexpected error occurred."),
                                            status_code=500)
            duration = (time.perf_counter() - started) * 1000
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            metrics.record_request(request.method, path, response.status_code, duration, request_id)
            response.headers["X-Request-ID"] = request_id
            if request.method != "OPTIONS":
                log.info("request", extra={"method": request.method, "path": path, "status": response.status_code,
                                           "duration_ms": round(duration, 2)})
            return response
        finally:
            request_id_var.reset(token)

    install_error_handlers(app)
    for module in (system, auth, users, exams, questions, attempts, results, sql_lab, db_meta):
        app.include_router(module.router)
    return app


app = create_app()
