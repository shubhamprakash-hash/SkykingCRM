from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.core.database import Base, engine, SessionLocal
from app.routers import auth, tickets, dashboard, customers
from app.services.sync_service import sync_tickets

settings = get_settings()
scheduler = AsyncIOScheduler()


def scheduled_sync_job():
    db = SessionLocal()
    try:
        result = sync_tickets(db)
        print(f"[msg91-sync] {result}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # create tables (use Alembic migrations in production instead)
    Base.metadata.create_all(bind=engine)

    # Run an immediate sync on startup so the CRM has data as soon as the
    # server is up -- no manual "Refresh/Sync" click needed for the mock
    # data to appear. The recurring interval job still runs after this for
    # ongoing updates once a real MSG91 feed is connected.
    scheduled_sync_job()

    scheduler.add_job(scheduled_sync_job, "interval",
                       seconds=settings.MSG91_SYNC_INTERVAL_SECONDS, id="msg91_sync")
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(tickets.router)
app.include_router(dashboard.router)
app.include_router(customers.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}
