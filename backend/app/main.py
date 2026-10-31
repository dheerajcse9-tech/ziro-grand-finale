from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
import logging

from .config import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
for _n in ("httpx", "httpcore", "google_genai", "chromadb"):
    logging.getLogger(_n).setLevel(logging.WARNING)
from .routers import agent, content, evaluation, monitor, demo as demo_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    from .seed_loader import seed_tenant
    from .agent.domain import OS_DOMAIN, save_config
    rep = seed_tenant(get_settings().default_tenant_id)
    if rep["missing_pdfs"] or rep["missing_captions"]:
        import logging
        logging.getLogger("doubtloop").warning("seed incomplete: missing PDFs %s, missing captions %s (see backend/seed/)", rep["missing_pdfs"], rep["missing_captions"])
    from . import db as _db
    if not _db.row("SELECT 1 FROM agent_configs WHERE tenant_id=?", (get_settings().default_tenant_id,)):
        save_config(get_settings().default_tenant_id, OS_DOMAIN)
    yield


app = FastAPI(
    title="DoubtLoop AI",
    version="0.1.0",
    description="Reusable self-learning agent service: answer, clarify or escalate, with teacher-verified memory.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list({
        get_settings().frontend_origin,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    }),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "service": "doubtloop-api"}


app.include_router(content.router)
app.include_router(agent.router)
app.include_router(evaluation.router)
app.include_router(monitor.router)
app.include_router(demo_router.router)
