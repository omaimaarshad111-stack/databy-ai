from fastapi import APIRouter

from app.api.v1.analytics import router as analytics_router
from app.api.v1.auth import router as auth_router
from app.api.v1.assistant import router as assistant_router
from app.api.v1.connections import router as connections_router
from app.api.v1.health import router as health_router
from app.api.v1.sql import router as sql_router
from app.api.v1.workspace import router as workspace_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(assistant_router)
api_router.include_router(connections_router)
api_router.include_router(sql_router)
api_router.include_router(analytics_router)
api_router.include_router(workspace_router)
