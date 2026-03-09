from __future__ import annotations

from fastapi import FastAPI

from app.config import AppConfig
from app.dependencies import build_router, build_service


def create_app(config: AppConfig | None = None) -> FastAPI:
    app = FastAPI(title="Pallium", version="0.1.0")
    service = build_service(config)
    app.state.pallium_service = service
    app.include_router(build_router(service))
    return app


app = create_app()
