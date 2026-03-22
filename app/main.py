from __future__ import annotations

from fastapi import FastAPI

from app.config import AppConfig
from app.dependencies import build_router, build_service
from semantic.agent_conversation_memory_routing import RoutingOverrides


def create_app(config: AppConfig | None = None, routing_overrides: RoutingOverrides | None = None) -> FastAPI:
    app = FastAPI(title="Pallium", version="0.1.0")
    service = build_service(config, routing_overrides=routing_overrides)
    app.state.pallium_service = service
    app.include_router(build_router(service))
    return app

