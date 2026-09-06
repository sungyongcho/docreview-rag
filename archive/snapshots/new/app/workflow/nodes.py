"""Pure retrieve, grade, check, and report state transitions."""

from __future__ import annotations

from collections.abc import Sequence

from app.llm import (
    AnswerDecision,
    BudgetExceeded,
    ProviderRefusal,
    ProviderResult,
    RelevanceJudgment,
    SchemaRejected,
)
from app.retrieval import ChunkHit
from app.workflow.types import (
    CitationsFiltered,
    ContextTruncated,
    DocumentQuotaApplied,
    DuplicateEvidenceText,
    DuplicateRetrievedChunks,
    EvidenceCitation,
    GradeCoverageIncomplete,
    GradeReferencesFiltered,
    ProviderFailure,
    RelevanceBelowThreshold,
    RetrievalEmpty,
    SupportedWithoutCitations,
    WorkflowReport,
    WorkflowState,
)


def _unique_hits(hits: Sequence[ChunkHit]) -> tuple[tuple[ChunkHit, ...], tuple[int, ...]]:
    unique: list[ChunkHit] = []
    duplicates: list[int] = []
    seen: set[int] = set()
    for hit in hits:
        if not isinstance(hit, ChunkHit):
            raise TypeError("retrieve_node hits must be ChunkHit values")
        if hit.chunk_id in seen:
            duplicates.append(hit.chunk_id)
            continue
        seen.add(hit.chunk_id)
        unique.append(hit)
    return tuple(unique), tuple(dict.fromkeys(duplicates))


def _text_unique_hits(
    hits: tuple[ChunkHit, ...],
) -> tuple[tuple[ChunkHit, ...], tuple[int, ...], tuple[int, ...]]:
    kept: list[ChunkHit] = []
    removed: list[int] = []
    kept_for_removed: list[int] = []
    owner_by_text: dict[str, int] = {}
    for hit in hits:
        body = " ".join(hit.body.split())
        owner = owner_by_text.get(body)
        if owner is not None:
            removed.append(hit.chunk_id)
            kept_for_removed.append(owner)
            continue
        owner_by_text[body] = hit.chunk_id
        kept.append(hit)
    return tuple(kept), tuple(removed), tuple(kept_for_removed)


def _document_quota_hits(
    hits: tuple[ChunkHit, ...],
    max_hits_per_document: int,
) -> tuple[tuple[ChunkHit, ...], tuple[int, ...]]:
    kept: list[ChunkHit] = []
    dropped: list[int] = []
    taken: dict[str, int] = {}
    for hit in hits:
        used = taken.get(hit.doc_id, 0)
        if used >= max_hits_per_document:
            dropped.append(hit.chunk_id)
            continue
        taken[hit.doc_id] = used + 1
        kept.append(hit)
    return tuple(kept), tuple(dropped)


def _context_hits(
    hits: tuple[ChunkHit, ...],
    max_context_chars: int,
) -> tuple[tuple[ChunkHit, ...], tuple[int, ...]]:
    selected: list[ChunkHit] = []
    dropped: list[int] = []
    used = 0
    for hit in hits:
        separator = 2 if selected else 0
        required = separator + len(hit.index_text)
        if used + required <= max_context_chars:
            selected.append(hit)
            used += required
        else:
            dropped.append(hit.chunk_id)
    return tuple(selected), tuple(dropped)


def retrieve_node(state: WorkflowState, hits: Sequence[ChunkHit]) -> WorkflowState:
    """Select ``k`` distinct evidence units and apply the whole-chunk context limit.

    Selection narrows an over-fetched list in four passes before the context
    budget runs: identity duplicates, then body-text duplicates, then one
    document's quota, then the cut to ``k``. Every pass records what it removed,
    because a silent drop hides the retrieval behavior that caused it.
    """
    unique, duplicates = _unique_hits(hits)
    distinct, text_removed, text_kept = _text_unique_hits(unique)
    within_quota, over_quota = _document_quota_hits(distinct, state.max_hits_per_document)
    selected = within_quota[: state.k]
    evidence, dropped = _context_hits(selected, state.max_context_chars)
    reasons = list(state.reasons)
    if duplicates:
        reasons.append(DuplicateRetrievedChunks(chunk_ids=duplicates))
    if text_removed:
        reasons.append(
            DuplicateEvidenceText(
                removed_chunk_ids=text_removed,
                kept_chunk_ids=text_kept,
            )
        )
    if over_quota:
        reasons.append(
            DocumentQuotaApplied(
                dropped_chunk_ids=over_quota,
                max_hits_per_document=state.max_hits_per_document,
            )
        )
    if not selected:
        reasons.append(
            RetrievalEmpty(
                query=state.query,
                k=state.k,
                filters=state.filters,
            )
        )
    if dropped:
        reasons.append(
            ContextTruncated(
                dropped_chunk_ids=dropped,
                max_context_chars=state.max_context_chars,
            )
        )
    return state.model_copy(
        update={
            "retrieved_hits": selected,
            "evidence": evidence,
            "reasons": tuple(reasons),
            "node_path": (*state.node_path, "retrieve"),
        }
    )


def _provider_failure(
    node: str,
    result: ProviderResult[object],
) -> ProviderFailure:
    refusal = result.refusal
    if isinstance(refusal, SchemaRejected):
        details = refusal.errors
    elif isinstance(refusal, BudgetExceeded):
        details = (f"{refusal.which}: used={refusal.used} limit={refusal.limit}",)
    elif isinstance(refusal, ProviderRefusal):
        details = (refusal.message,)
    else:
        raise ValueError("failed provider result must contain a recognized typed refusal")
    return ProviderFailure(
        node=node,
        status=result.status,
        details=details,
    )


def grade_node(
    state: WorkflowState,
    result: ProviderResult[RelevanceJudgment],
) -> WorkflowState:
    """Keep only relevant grades tied to supplied evidence and record omissions."""
    path = (*state.node_path, "grade")
    if result.status != "ok":
        failure = _provider_failure("grade", result)
        return state.model_copy(
            update={
                "failure": failure,
                "reasons": (*state.reasons, failure),
                "node_path": path,
            }
        )
    if not isinstance(result.parsed, RelevanceJudgment):
        raise TypeError("grade result must contain RelevanceJudgment")

    allowed = {hit.chunk_id for hit in state.evidence}
    returned = {grade.chunk_id for grade in result.parsed.grades}
    removed = tuple(
        grade.chunk_id for grade in result.parsed.grades if grade.chunk_id not in allowed
    )
    missing = tuple(hit.chunk_id for hit in state.evidence if hit.chunk_id not in returned)
    relevant = {
        grade.chunk_id
        for grade in result.parsed.grades
        if grade.chunk_id in allowed and grade.relevant
    }
    relevant_in_evidence_order = tuple(
        hit.chunk_id for hit in state.evidence if hit.chunk_id in relevant
    )
    reasons = list(state.reasons)
    if removed:
        reasons.append(GradeReferencesFiltered(removed_chunk_ids=removed))
    if missing:
        reasons.append(GradeCoverageIncomplete(missing_chunk_ids=missing))
    if not relevant_in_evidence_order:
        reasons.append(
            RelevanceBelowThreshold(
                relevant_count=0,
                candidate_count=len(state.evidence),
                minimum_required=1,
            )
        )
    return state.model_copy(
        update={
            "relevant_chunk_ids": relevant_in_evidence_order,
            "reasons": tuple(reasons),
            "node_path": path,
        }
    )


def check_node(
    state: WorkflowState,
    result: ProviderResult[AnswerDecision],
) -> WorkflowState:
    """Filter unsupported citations and downgrade uncited supported decisions."""
    path = (*state.node_path, "check")
    if result.status != "ok":
        failure = _provider_failure("check", result)
        return state.model_copy(
            update={
                "failure": failure,
                "reasons": (*state.reasons, failure),
                "node_path": path,
            }
        )
    if not isinstance(result.parsed, AnswerDecision):
        raise TypeError("check result must contain AnswerDecision")

    decision = result.parsed
    allowed = set(state.relevant_chunk_ids)
    kept = tuple(chunk_id for chunk_id in decision.citation_chunk_ids if chunk_id in allowed)
    removed = tuple(chunk_id for chunk_id in decision.citation_chunk_ids if chunk_id not in allowed)
    reasons = list(state.reasons)
    if removed:
        reasons.append(CitationsFiltered(removed_chunk_ids=removed, kept_chunk_ids=kept))

    if decision.label == "SUPPORTED" and not kept:
        reasons.append(SupportedWithoutCitations(requested_chunk_ids=decision.citation_chunk_ids))
        guarded = AnswerDecision(
            label="NOT_IN_DOCS",
            answer="NOT_IN_DOCS",
            citation_chunk_ids=(),
            reason="The supported answer was downgraded because no valid citation remained.",
        )
    elif decision.label == "SUPPORTED":
        guarded = AnswerDecision(
            label="SUPPORTED",
            answer=decision.answer,
            citation_chunk_ids=kept,
            reason=decision.reason,
        )
    else:
        guarded = decision
    return state.model_copy(
        update={
            "decision": guarded,
            "reasons": tuple(reasons),
            "node_path": path,
        }
    )


def _absence_rationale(state: WorkflowState) -> str:
    if not state.retrieved_hits:
        return "No evidence was retrieved for the query."
    if not state.evidence:
        return "Retrieved evidence could not fit within the context budget."
    if not state.relevant_chunk_ids:
        return "No supplied evidence met the relevance threshold."
    return "The guarded decision did not establish supported evidence."


def report_node(state: WorkflowState) -> WorkflowState:
    """Build the final answer only from guarded decisions and validated evidence."""
    citations_by_id = {hit.chunk_id: hit for hit in state.evidence}
    if state.decision is not None and state.decision.label == "SUPPORTED":
        citations = tuple(
            EvidenceCitation(
                chunk_id=chunk_id,
                doc_id=citations_by_id[chunk_id].doc_id,
                citation=citations_by_id[chunk_id].citation,
                start_char=citations_by_id[chunk_id].start_char,
                end_char=citations_by_id[chunk_id].end_char,
                source_sha256=citations_by_id[chunk_id].source_sha256,
            )
            for chunk_id in state.decision.citation_chunk_ids
        )
        report = WorkflowReport(
            label="SUPPORTED",
            answer=state.decision.answer,
            citations=citations,
            rationale=state.decision.reason,
            reasons=state.reasons,
        )
    else:
        rationale = (
            state.decision.reason if state.decision is not None else _absence_rationale(state)
        )
        report = WorkflowReport(
            label="NOT_IN_DOCS",
            answer="NOT_IN_DOCS",
            citations=(),
            rationale=rationale,
            reasons=state.reasons,
        )
    return state.model_copy(
        update={
            "report": report,
            "node_path": (*state.node_path, "report"),
        }
    )
