"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import init_app
from app.api import router as api_router
from app.api.endpoints.websocket import router as websocket_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.metrics import configure_metrics
from app.core.rate_limit import configure_rate_limiting
from app.core.sentry import configure_sentry
from app.services.document_parser import PDF_TEXT_PARSER_VERSION
from app.services.medical.ai.versions import (
    ANALYSIS_PIPELINE_VERSION,
    MEDICAL_INSIGHT_API_CONTRACT_VERSION,
)

import uvicorn


configure_sentry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prepare runtime directories when the application starts."""
    init_app()
    print("=" * 50)
    print(f"{settings.PROJECT_NAME} v{settings.VERSION}")
    print(f"API Docs: http://localhost:{settings.PORT}/docs")
    print(f"Environment: {settings.ENVIRONMENT}")
    print("=" * 50)
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="GraphMind - AI-powered Knowledge Graph Platform",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-GraphMind-Backend-Commit",
        "X-GraphMind-Frontend-Commit",
        "X-GraphMind-Parser-Version",
        "X-GraphMind-Analysis-Pipeline",
        "X-GraphMind-Insight-Contract",
        "X-GraphMind-Analysis-Model",
    ],
)


@app.middleware("http")
async def attach_runtime_versions(request, call_next):
    response = await call_next(request)
    response.headers["X-GraphMind-Backend-Commit"] = settings.GIT_SHA or "unknown"
    response.headers["X-GraphMind-Frontend-Commit"] = request.headers.get(
        "X-GraphMind-Frontend-Commit", "unknown"
    )
    response.headers["X-GraphMind-Parser-Version"] = PDF_TEXT_PARSER_VERSION
    response.headers["X-GraphMind-Analysis-Pipeline"] = ANALYSIS_PIPELINE_VERSION
    response.headers["X-GraphMind-Insight-Contract"] = MEDICAL_INSIGHT_API_CONTRACT_VERSION
    response.headers["X-GraphMind-Analysis-Model"] = settings.MEDICAL_AI_MODEL
    return response

configure_rate_limiting(app)
configure_metrics(app)
register_error_handlers(app)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)
app.include_router(websocket_router)


@app.get("/")
async def root():
    """Return a lightweight service status."""
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running",
    }


@app.get("/health")
async def health_check():
    """Return upload directory health details."""
    return {
        "status": "healthy",
        "upload_dir_exists": os.path.exists(settings.UPLOAD_DIR),
        "upload_dir": settings.UPLOAD_DIR,
    }


if __name__ == "__main__":

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
    )
