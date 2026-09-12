from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.jobs import init_jobs_api, router as jobs_router
from app.api.plans import router as plans_router
from app.config import get_settings
from app.services.stdio_utf8 import ensure_utf8_stdio

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_utf8_stdio()
    settings = get_settings()
    init_jobs_api(settings)
    yield


app = FastAPI(
    title="Handover Learning Pack API",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(jobs_router)
app.include_router(plans_router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


@app.get("/health")
def health():
    return {"status": "ok"}
