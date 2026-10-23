from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once when the server starts, before any requests are served.
    init_db()
    yield


app = FastAPI(title="Taskmaster Menu", lifespan=lifespan)


@app.get("/health")
def health():
    """Quick check that the server is up. Handy at the venue."""
    return {"status": "ok"}