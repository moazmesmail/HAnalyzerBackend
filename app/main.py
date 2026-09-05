from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.features.identity.admin_router import router as admin_router
from app.features.identity.router import router as auth_router
from app.features.videos.router import router as videos_router
from app.platform.config import get_settings
from app.platform.errors import register_error_handlers
from app.platform.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):51(7[3-9]|8[0-3])",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def origin_guard(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and not settings.is_allowed_origin(origin):
                return JSONResponse(
                    status_code=403,
                    content={
                        "code": "INVALID_ORIGIN",
                        "message": "Request origin is not allowed.",
                    },
                )
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(f"{settings.api_prefix}/health")
    def api_health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_router, prefix=settings.api_prefix)
    app.include_router(admin_router, prefix=settings.api_prefix)
    app.include_router(videos_router, prefix=settings.api_prefix)
    register_error_handlers(app)
    return app


app = create_app()
