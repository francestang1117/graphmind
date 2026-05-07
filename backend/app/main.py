"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import init_app
from app.api import router as api_router
from app.api.endpoints.websocket import router as websocket_router
from app.core.config import settings
from app.core.rate_limit import configure_rate_limiting

import uvicorn


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
)

configure_rate_limiting(app)
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
