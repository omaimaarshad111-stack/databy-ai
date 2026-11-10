from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from collections.abc import Awaitable, Callable
import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging, request_id_context
from app.core.rate_limit import auth_rate_limiter
from app.database_targets.connection_manager import connection_manager
from app.db.session import engine

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting %s", settings.app_name)
    try:
        yield
    finally:
        connection_manager.dispose_all()
        engine.dispose()
        logger.info("Shutting down %s", settings.app_name)


is_production = settings.app_env.lower() == "production"
app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
    openapi_url=None if is_production else "/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Content-Disposition", "X-Request-ID"],
)
app.include_router(api_router, prefix=settings.api_prefix)


@app.middleware("http")
async def request_context_and_auth_rate_limit(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = uuid4().hex
    request.state.request_id = request_id
    context_token = request_id_context.set(request_id)
    try:
        endpoint = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        if endpoint in {"login", "register"} and request.method == "POST":
            client = request.client.host if request.client is not None else "unknown"
            limit = (
                settings.auth_login_rate_limit
                if endpoint == "login"
                else settings.auth_register_rate_limit
            )
            retry_after = auth_rate_limiter.check(
                client,
                endpoint,
                limit=limit,
                window_seconds=settings.auth_rate_limit_window_seconds,
            )
            if retry_after is not None:
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Too many authentication attempts. Try again later."},
                    headers={"Retry-After": str(retry_after)},
                )
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_context.reset(context_token)


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    _: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = [
        {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.error(
        "Unhandled request error method=%s path=%s error_type=%s",
        request.method,
        request.url.path,
        type(exc).__name__,
        extra={"request_id": getattr(request.state, "request_id", "-")},
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected server error occurred."},
    )
