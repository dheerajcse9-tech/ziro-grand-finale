"""Deterministic decision policy. Confidence is computed from retrieval evidence, never taken from the LLM's self-report."""
from dataclasses import dataclass

from .domain import DomainConfig


@dataclass
class Decision:
    decision: str            # ANSWER | CLARIFY | ESCALATE
    code: str
    reason: str
    confidence: float = 0.0
    reuse: bool = False


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def evidence_confidence(top_similarity: float, coverage: float, n_supporting: int) -> float:
    """0.45 * normalised top similarity + 0.35 * term/claim coverage + 0.20 * corroboration (2+ supporting chunks)."""
    return round(0.45 * _clamp((top_similarity - 0.25) / 0.5) + 0.35 * _clamp(coverage) + 0.20 * min(1.0, n_supporting / 2), 3)


def decide(cfg: DomainConfig, *, ambiguous: bool, clarify_rounds: int, retrieval_error: str | None, reuse_similarity: float | None,
           n_relevant: int, top_similarity: float, assessment: dict, n_supporting: int) -> Decision:
    t = cfg.thresholds
    if ambiguous and cfg.clarification_enabled and clarify_rounds < t.max_clarification_rounds:
        return Decision("CLARIFY", "ambiguous_question", "The question is missing information needed to answer it.")
    if reuse_similarity is not None:
        return Decision("ANSWER", "approved_resolution_reused", "A matching teacher-approved resolution addresses this question.",
                        confidence=round(_clamp((reuse_similarity - 0.25) / 0.5), 3), reuse=True)
    if retrieval_error:
        return Decision("ESCALATE", "retrieval_unavailable", f"Evidence retrieval failed ({retrieval_error}); not answering without evidence.")
    if n_relevant == 0:
        if cfg.escalation.on_no_evidence:
            return Decision("ESCALATE", "no_evidence", "No relevant evidence was found in the course materials.")
    if assessment.get("contradiction") and cfg.escalation.on_contradiction:
        return Decision("ESCALATE", "contradictory_evidence", f"Sources conflict: {assessment.get('contradiction_detail') or 'materially contradictory evidence'}.")
    conf = evidence_confidence(top_similarity, assessment.get("coverage", 0), n_supporting)
    if not assessment.get("supported") or n_supporting < t.min_evidence_chunks or assessment.get("coverage", 0) < t.min_term_coverage:
        return Decision("ESCALATE", "insufficient_evidence", "Retrieved material does not adequately cover the question.", confidence=conf)
    if conf < t.answer_confidence and cfg.escalation.on_low_confidence:
        return Decision("ESCALATE", "low_confidence", f"Evidence confidence {conf} is below the required {t.answer_confidence}.", confidence=conf)
    return Decision("ANSWER", "sufficient_evidence", "Sufficient supporting evidence found.", confidence=conf)
