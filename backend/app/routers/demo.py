"""Demo data management + jury demo suite endpoints (demo tenant only; admin token or loopback)."""
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from .. import demo, demo_suite
from ..config import get_settings
from ..deps import tenant

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])


def admin(request: Request, x_admin_token: str | None = Header(default=None), t: str = Depends(tenant)) -> str:
    if t != demo.tenant_id():
        raise HTTPException(403, "Demo tools are only available for the designated demo tenant.")
    tok = get_settings().admin_token
    if tok:
        if not x_admin_token or not hmac.compare_digest(x_admin_token, tok):
            raise HTTPException(401, "Admin token required (X-Admin-Token).")
    elif (request.client.host if request.client else "") not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(403, "No ADMIN_TOKEN is configured, so demo tools accept local requests only.")
    return t


class ResetIn(BaseModel):
    confirmation_token: str
    confirm: bool = False


@router.get("/status")
def status(t: str = Depends(admin)):
    return demo.status(t)


@router.post("/reset/prepare", summary="Step 1: returns exactly what a reset would delete/preserve, plus a one-time confirmation token")
def prepare(t: str = Depends(admin)):
    return demo.prepare(t)


@router.post("/reset", summary="Step 2: execute the reset (requires the confirmation token and confirm=true)")
def reset(body: ResetIn, t: str = Depends(admin)):
    if not body.confirm:
        raise HTTPException(400, "Explicit confirmation required (confirm=true).")
    try:
        return demo.reset(t, body.confirmation_token, actor="admin")
    except demo.ResetError as e:
        raise HTTPException(409, str(e))


@router.get("/tests")
def tests(t: str = Depends(admin)):
    return demo_suite.overview(t)


@router.post("/tests/{n}/run", summary="Run one jury scenario against the real agent (may take a while when the LLM provider is slow)")
def run(n: int, t: str = Depends(admin)):
    try:
        return demo_suite.run_test(t, n)
    except KeyError:
        raise HTTPException(404, "Unknown test.")
