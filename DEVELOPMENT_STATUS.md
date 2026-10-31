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

## Phase 3 — Gemini integration
**Status: integration code complete and tested with mocks; the real Gemini smoke test FAILED (provider-side 503/504), so live Gemini operation is NOT confirmed.**
- Model `gemini-3.8-flash` exists and supports `generateContent` (metadata lookup succeeded). SDK `google-genai` 2.34.0. Key is read from `backend/.env` only (git-ignored), never logged or sent to the frontend.
- One real smoke test (question "What is a race condition?"): every Gemini request (understand, assess, compose; 1 retry each) returned HTTP 503/504. The agent fell back to local-demo and still answered with correct PDF page + video citations (`llm_mode=gemini+local-fallback`). No second live attempt was made (budget rule).
- Hardening: request timeout (`GEMINI_TIMEOUT_S`), bounded retry on 429/5xx/timeout (`GEMINI_MAX_RETRIES`), per-request skip after first failure, process-level cooldown circuit breaker (`GEMINI_COOLDOWN_S`), JSON/empty-response validation, unknown-id filtering, rejection of answers that invent page/timestamp references, evidence delimiter-tag neutralisation, security preamble in the system prompt, deterministic numeric-contradiction check alongside the model's, usage logging (tokens, latency) without keys or question text.
- Decisions stay in Python (retrieval, confidence, ANSWER/CLARIFY/ESCALATE, citations built from retrieved metadata). Only teacher approval writes trusted memory.
- Tests: 30 backend passed (16 new mocked-Gemini tests: parsing, retry, rate limit, timeout, invalid JSON, injection, invented citations, secrets, answer, clarify, escalate, contradiction, fallback, approval + reuse). Frontend tsc/eslint/build clean. Evaluation (local-demo, regression): 17/20, unchanged from before (decision accuracy 100%, evidence support 100%). A Gemini-mode evaluation was not run (would need ~60 live calls and the API was returning 5xx).

## Phase 4 — Agentic workflow visualization

- **Events**: `backend/app/agent/events.py` (`Recorder`) persists structured events to the `agent_events` table and optionally pushes them to a live sink. Emitted from the real orchestrator (understand/retrieve/verify/decide/respond/memory + each LLM call and tool call), `memory.approve/reject` (teacher approval, memory save, same run timeline), and the ingestion pipeline (extract/chunk/embed/index/validate). Payloads carry no keys, user ids or session ids.
- **API**: `POST /api/v1/agent/ask/stream` (SSE; `/agent/ask` unchanged), `GET /events/runs`, `/events/runs/{id}`, `/escalations/{id}/events`, `/ingestion/{rid}/events`, `/resources/{rid}/search`, `/admin/stats`.
- **UI**: live activity panel in the tutor, orchestration page `/agents`, teacher investigation history + approval receipt + approved-knowledge search, admin stats / ingestion pipeline / retrieval test / run monitor.
- **Not implemented**: authentication and role permissions (none existed; the three workspaces are separate routes, not access-controlled). The six "agents" are stages of one deterministic orchestrator (some call the LLM), not independent processes.
- Tests: `backend/tests/test_events.py` (6).
