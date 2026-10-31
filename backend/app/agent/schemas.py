from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    tenant_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=96)
    user_id: str | None = Field(default=None, max_length=96)
    subject_id: str | None = None
    topic_id: str | None = None
    context: dict[str, Any] | None = Field(default=None, description="Optional free-form client context (e.g. page URL)")


class Source(BaseModel):
    source_type: str
    source_id: str
    source_name: str
    page: int | None = None
    timestamp_start: float | None = None
    timestamp_end: float | None = None
    youtube_id: str | None = None
    url: str | None = None
    filename: str | None = None
    heading: str | None = None
    timestamp_status: str | None = Field(default=None, description="video only: 'caption' (from caption timing), 'verified', or 'unverified' (user-supplied, pending verification)")
    trust: str = "curated"
    origin: str | None = None
    excerpt: str | None = None
    chunk_id: str | None = None


class TraceStep(BaseModel):
    step: str
    ok: bool = True
    detail: str = ""
    ms: int = 0


class AgentResponse(BaseModel):
    decision: Literal["ANSWER", "CLARIFY", "ESCALATE"]
    answer: str | None = None
    clarification_question: str | None = None
    escalation_id: int | None = None
    message: str | None = None
    confidence: float = 0.0
    sources: list[Source] = []
    reason: str
    reason_code: str
    answered_from: Literal["evidence", "approved_resolution", "none"] = "none"
    session_id: str
    llm_mode: str
    run_id: str | None = Field(default=None, description="Execution-event run id; GET /api/v1/events/runs/{run_id}")
    trace: list[TraceStep] = []
