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

## Phase 2 — real dataset integration (latest)
**Status: READY FOR GEMINI INTEGRATION** (set `GEMINI_API_KEY` in `backend/.env`; local-demo remains the fallback).

**Ingestion (demo-university tenant, from `scripts/ingest_stats.py`)**: 5 PDFs / 85 pages / 282 chunks · 5 videos · 111 caption chunks (real YouTube captions) · 31 user-supplied segments (all `unverified`) · 424 vectors total (282 + 111 + 31). Placeholder/sample resources in the active dataset: none (old sample PDFs and unrelated videos removed; eval-only fixtures live in the isolated `eval-tenant`).
**PDF extraction**: PyMuPDF with running header/footer removal, section headings (kept as chunk metadata), tables as `a | b` rows, page numbers and original filename on every chunk. Embedded images (82 across the PDFs, incl. Gantt charts and worked-example figures) are NOT text-searchable and not OCR'd.
**Citations**: PDF = filename + page; video = `watch?v=ID&t=START`, with `timestamp_status` = `caption` (from caption timing) or `unverified` (user-supplied, flagged in UI). Title-only segments act as "watch this part" pointers, never as answer evidence. Video IDs verified via oEmbed; caption end times (1250/630/1020/740/1420 s) agree with the supplied durations/last timestamps (corroboration, not proof).
**Local retrieval validation** (`scripts/validate_retrieval.py`, real agent, local-demo): 12/13 with workspace topic context, 11/13 without. Failures: "independent vs cooperative processes" (cites a less relevant synchronization page instead of Process-Management p7); without topic context also "mutual exclusion and hold and wait" (cites the lock-variable section). All 3 unsupported questions correctly escalated; no fabricated citations; all video URLs correct.
**Evaluation** (20 cases, real agent, local-demo): 17/20 pass; decision accuracy 100%, evidence support 100%, unsupported-answer rate 0%, video-link validity 100%, tool success 100%. Failures (pdf-1, pdf-4, pdf-6) are incomplete *extractive* answers with correct citations; Gemini composition is expected to help.
**Tests**: backend 14 passed / 0 failed; frontend tsc, eslint, build clean; live HTTP E2E + restart persistence passed.
**Limitations**: Gemini path still untested (no key here); explanations/keywords for segments were not supplied so none are invented; contradiction detection without Gemini = small numeric counts only; seed PDFs/captions are git-ignored (third-party content, public repo) so a fresh clone needs `backend/seed/README.md` steps; the earlier commit `ac61f31`/`8abf3e6` history still contains 5 caption JSON files from the superseded sample videos.
