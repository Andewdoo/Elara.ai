from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.observability import initialize_api_sentry
from app.routes import auth_router, history_router, uploads_router, verifications_router
from app.security import SecurityHeadersMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    initialize_api_sentry(settings)
    app = FastAPI(title=settings.app_name, version="1.0.0")
    app.add_middleware(
        SecurityHeadersMiddleware,
        production=settings.environment in {"staging", "production"},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
    )
    app.include_router(auth_router)
    app.include_router(history_router)
    app.include_router(uploads_router)
    app.include_router(verifications_router)

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
