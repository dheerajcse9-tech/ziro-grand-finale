# DoubtLoop AI — Development Status

Run backend: `cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000` (Swagger at `/docs`)
Python env: `uv venv --python 3.12 backend/.venv && uv pip install --python backend/.venv/bin/python -r backend/requirements.txt`

## Milestones
| # | Milestone | Status | Commit |
|---|-----------|--------|--------|
| 1 | Backend foundation (config, SQLite schema, /health) | done | c5b1924 |
| 2 | PDF/transcript ingestion, Chroma retrieval, OS seed data (4 topics, 4 PDFs, 5 videos w/ real captions) | done, 4 tests | 9dd9bb6 |
| 3 | Agent engine (orchestrator, 4 tools, policy, memory, approval, REST API) | done, 11 tests pass | see git log |

## Decisions
- Python 3.12 venv (3.14 lacks torch/chroma wheels). Tenant isolation via `tenant_id` on every row and vector.
- No Gemini key => labelled `local-demo` mode (extractive answers, deterministic checks). Never reported as Gemini.
