# DoubtLoop AI — Development Status

Run backend: `cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000` (Swagger at `/docs`)
Python env: `uv venv --python 3.12 backend/.venv && uv pip install --python backend/.venv/bin/python -r backend/requirements.txt`

## Milestones
| # | Milestone | Status | Commit |
|---|-----------|--------|--------|
| 1 | Backend foundation (config, SQLite schema, /health) | done | c5b1924 |
| 2 | PDF/transcript ingestion, Chroma retrieval, OS seed data (4 topics, 4 PDFs, 5 videos w/ real captions) | done, 4 tests | 9dd9bb6 |
| 3 | Agent engine (orchestrator, 4 tools, policy, memory, approval, REST API) | done, 11 tests pass | acc0393 |
| 5 | Frontend: student dashboard, workspace (video seek, PDF page, tutor), teacher, admin, evaluation pages | done; build + live HTTP E2E incl. restart persistence verified | see git log |
| 4 | Evaluation framework (18 cases, runner, API) | done; last real run in local-demo mode: 17/18 pass | see git log |

## Decisions
- Python 3.12 venv (3.14 lacks torch/chroma wheels). Tenant isolation via `tenant_id` on every row and vector.
- No Gemini key => labelled `local-demo` mode (extractive answers, deterministic checks). Never reported as Gemini.

## Progress (latest)
**Completed:** backend engine (ingestion, Chroma retrieval, orchestrator, 4 tools, policy, approval memory, REST API + Swagger), 18-case evaluation, all 5 UI pages, timestamped-segment metadata ingestion (idempotent upsert, per-segment embedding reuse, verified/unverified citation rules).
**Tests:** backend `pytest` 13 passed, 0 failed. Frontend `tsc`, eslint, `next build` clean. Live HTTP E2E (answer, clarify→continue, escalate, approve, restart, reuse) passed.
**Evaluation (local-demo mode, no Gemini key):** 17/18 cases pass; known failure vid-3 (extractive answer omits expected term). Re-run from /evaluation.
**In progress / remaining:** (1) real Gemini path is implemented but UNTESTED (no API key in this environment); (2) external dataset (5 Gate Smashers lectures, verified segments, PDFs) not yet received — current video data = real YouTube captions for 5 *other* Gate Smashers/Jenny's videos, PDFs are original sample notes; (3) semantic contradiction detection needs Gemini (local heuristic = numeric counts only).
**Known limits:** segment import via API/admin JSON only (no CSV); resolution keywords/PDF refs not captured on approval.
