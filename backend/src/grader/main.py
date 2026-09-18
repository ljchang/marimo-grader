"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from grader.api import admin, auth, grading, offerings, public, roster, storage, submissions
from grader.config import get_settings

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Grader API",
        version="0.1.0",
        docs_url="/api/docs" if s.env != "prod" else None,
        openapi_url="/api/openapi.json",
    )
    # CORS is only for the notebook widget (Bearer tokens). The Svelte UI is same-origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_origin_regex=s.cors_regex,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(HTTPException)
    async def _http_exc(_: Request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            body = {"error": detail}
        else:
            body = {"error": {"code": "error", "message": str(detail)}}
        return JSONResponse(
            body, status_code=exc.status_code, headers=getattr(exc, "headers", None)
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(_: Request, exc: RequestValidationError):
        return JSONResponse(
            {
                "error": {
                    "code": "validation",
                    "message": "invalid request",
                    "details": exc.errors(),
                }
            },
            status_code=422,
        )

    @app.get("/api/health")
    def health():
        cur = get_settings()  # read at request time so mode flips are visible without restart
        return {
            "ok": True,
            "env": cur.env,
            "auth_mode": cur.auth_mode,
            "submissions_enabled": cur.auth_mode != "disabled",
            # Lets the sign-in page offer the link form only when it will work.
            "email_login_enabled": cur.email_login_enabled,
        }

    for r in (
        auth.router,
        offerings.router,
        submissions.router,
        grading.router,
        roster.router,
        storage.router,
        admin.router,
    ):
        app.include_router(r, prefix=API_PREFIX)
    app.include_router(public.router)  # /a/... aliases live at the root
    return app


app = create_app()


def run() -> None:  # console script
    import uvicorn

    uvicorn.run("grader.main:app", host="0.0.0.0", port=8000, reload=get_settings().env == "dev")
