"""FastAPI Application factory configuring routes, middleware, and RFC 9457 error handling."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dq_scoring.presentation.api.config import ApiSettings, get_api_settings
from dq_scoring.presentation.api.errors import register_exception_handlers
from dq_scoring.presentation.api.middleware import SecurityHeadersMiddleware
from dq_scoring.presentation.api.routes import (
    assessment_routes,
    asset_routes,
    auth_routes,
    import_routes,
    operations_routes,
    policy_routes,
    privacy_routes,
    privacy_rule_routes,
    privacy_scan_routes,
    ruleset_routes,
    run_routes,
    template_routes,
    text_routes,
)


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    """Initialize and configure FastAPI application instance."""
    cfg = settings or get_api_settings()

    app = FastAPI(
        title="DQ Scoring Engine API",
        version="1.0.0",
        description="Deterministic, Vectorized Multi-Tenant Data Quality Scoring System",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # 1. Register RFC 9457 Exception Handlers
    register_exception_handlers(app)

    # 2. Add Security and Sanitization Middlewares (AC-025)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 3. Include API Routers
    app.include_router(auth_routes.router)
    app.include_router(asset_routes.router)
    app.include_router(ruleset_routes.router)
    app.include_router(policy_routes.router)
    app.include_router(run_routes.router)
    app.include_router(assessment_routes.router)
    app.include_router(template_routes.router)
    app.include_router(import_routes.router)
    app.include_router(operations_routes.router)
    app.include_router(text_routes.router)
    app.include_router(privacy_routes.router)
    app.include_router(privacy_rule_routes.router)
    app.include_router(privacy_scan_routes.router)

    @app.get("/health", tags=["Health"])
    def health_check() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "healthy", "service": "dq-scoring-api"}

    return app


app = create_app()
