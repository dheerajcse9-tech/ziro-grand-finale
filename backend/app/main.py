from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .config import get_settings
from .routers import agent, content, evaluation


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    from .seed_loader import seed_tenant
    from .agent.domain import OS_DOMAIN, save_config
    if seed_tenant(get_settings().default_tenant_id)["seeded"]:
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
    allow_origins=list({get_settings().frontend_origin, "http://localhost:3000", "http://127.0.0.1:3000"}),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "service": "doubtloop-api"}


app.include_router(content.router)
app.include_router(agent.router)
app.include_router(evaluation.router)
