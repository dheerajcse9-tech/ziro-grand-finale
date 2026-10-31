"""Domain configuration: everything that makes the generic agent an 'Operating Systems tutor' lives here, not in agent code."""
from pydantic import BaseModel, Field

from .. import db


class Thresholds(BaseModel):
    min_relevance: float = Field(0.30, ge=0, le=1, description="Minimum cosine similarity for a chunk to count as candidate evidence")
    min_term_coverage: float = Field(0.5, ge=0, le=1, description="Share of the question's key terms the evidence must cover")
    answer_confidence: float = Field(0.45, ge=0, le=1, description="Computed (not self-reported) confidence required to answer")
    min_evidence_chunks: int = Field(1, ge=1)
    reuse_similarity: float = Field(0.62, ge=0, le=1, description="Similarity at which an approved resolution is considered a match")
    max_clarification_rounds: int = Field(1, ge=0, le=3)


class EscalationPolicy(BaseModel):
    on_no_evidence: bool = True
    on_contradiction: bool = True
    on_low_confidence: bool = True


class HumanApproval(BaseModel):
    required_for_memory: bool = True


class DomainConfig(BaseModel):
    name: str = "Generic Knowledge Assistant"
    instructions: str = "Answer only from the supplied evidence. If the evidence is insufficient, say so."
    sources: list[str] = Field(default_factory=lambda: ["pdf", "video", "resolution"], description="Knowledge source types the agent may search")
    thresholds: Thresholds = Thresholds()
    escalation: EscalationPolicy = EscalationPolicy()
    human_approval: HumanApproval = HumanApproval()
    tools: list[str] = Field(default_factory=lambda: ["search_knowledge_base", "search_solved_doubts", "create_escalation", "save_approved_resolution"])
    top_k: int = Field(6, ge=1, le=15)
    clarification_enabled: bool = True


OS_DOMAIN = DomainConfig(
    name="Operating Systems Tutor",
    instructions=("You are a teaching assistant for an Operating Systems course. Explain concepts clearly for undergraduate students "
                  "using only the provided course evidence (lecture transcripts, notes, and teacher-approved resolutions). "
                  "Never invent page numbers, timestamps or facts that are not in the evidence."),
)


def load_config(tenant_id: str) -> DomainConfig:
    r = db.row("SELECT config FROM agent_configs WHERE tenant_id=?", (tenant_id,))
    return DomainConfig.model_validate_json(r["config"]) if r else DomainConfig()


def save_config(tenant_id: str, cfg: DomainConfig) -> DomainConfig:
    db.execute("INSERT INTO agent_configs(tenant_id,config,updated_at) VALUES(?,?,?) ON CONFLICT(tenant_id) DO UPDATE SET config=excluded.config, updated_at=excluded.updated_at",
               (tenant_id, cfg.model_dump_json(), db.now()))
    return cfg
