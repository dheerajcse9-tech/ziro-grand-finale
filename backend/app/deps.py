from fastapi import Header, HTTPException, Query


def tenant(x_tenant_id: str | None = Header(default=None), tenant_id: str | None = Query(default=None)) -> str:
    """Tenant comes from the X-Tenant-ID header (preferred) or ?tenant_id=. Required on every tenant-scoped endpoint."""
    t = (x_tenant_id or tenant_id or "").strip()
    if not t or len(t) > 64:
        raise HTTPException(400, "tenant_id is required (X-Tenant-ID header or tenant_id query parameter).")
    return t
