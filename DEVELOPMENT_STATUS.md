# DoubtLoop AI — Development Status

Run backend: `cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000` (Swagger at `/docs`)
Python env: `uv venv --python 3.12 backend/.venv && uv pip install --python backend/.venv/bin/python -r backend/requirements.txt`

## Milestones
| # | Milestone | Status | Commit |
|---|-----------|--------|--------|
| 1 | Backend foundation (config, SQLite schema, /health) | done | see git log |

## Decisions
- Python 3.12 venv (3.14 lacks torch/chroma wheels). Tenant isolation via `tenant_id` on every row and vector.
- No Gemini key => labelled `local-demo` mode (extractive answers, deterministic checks). Never reported as Gemini.
