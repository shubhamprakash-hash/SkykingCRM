import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError
from app.config import get_settings
from app.database import Base, engine
from app import models  # noqa: F401
from app.routers import auth, tickets, branches, users, admin, reports
from app.services.errors import WorkflowError

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app):
    if get_settings().APP_ENV != "production":
        Base.metadata.create_all(engine)      # dev convenience; production runs `alembic upgrade head`
    yield


app = FastAPI(title="Skyking Complaint CRM", version="1.0.0", lifespan=lifespan)
s = get_settings()
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.CORS_ORIGINS.split(",") if o.strip()],
                   allow_methods=["*"], allow_headers=["*"], allow_credentials=False)
for r in (auth, tickets, branches, users, admin, reports):
    app.include_router(r.router)


@app.exception_handler(WorkflowError)
async def workflow_error(_: Request, e: WorkflowError):
    return JSONResponse(status_code=e.status_code, content={"detail": e.message, **e.extra})


@app.exception_handler(StaleDataError)
async def stale(_: Request, e: StaleDataError):
    return JSONResponse(status_code=409, content={"detail": "This complaint was changed by someone else. Reload and try again."})


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve the built React app when present (single-container deployments). API routes above take precedence.
import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
_static = os.environ.get("STATIC_DIR", os.path.join(os.path.dirname(__file__), "..", "static"))
if os.path.isdir(_static):
    app.mount("/assets", StaticFiles(directory=os.path.join(_static, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(404, "Not found")
        f = os.path.join(_static, path)
        return FileResponse(f if path and os.path.isfile(f) else os.path.join(_static, "index.html"))
