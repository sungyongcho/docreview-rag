"""Pure retrieve, grade, check, and report state transitions."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from app.llm.schemas import (
    AnswerDecision,
    BudgetExceeded,
    ProviderRefusal,
    ProviderResult,
    RelevanceJudgment,
    SchemaRejected,
)
from app.retrieval.types import ChunkHit
from app.workflow.prompts import evidence_budget_chars, evidence_chars
from app.workflow.types import (
    CitationsFiltered,
    ContextTruncated,
    DocumentQuotaApplied,
    DuplicateEvidenceText,
    DuplicateRetrievedChunks,
    EvidenceCitation,
    GradeCoverageIncomplete,
    GradeOrCheckNode,
    GradeReferencesFiltered,
    ProviderFailure,
    RelevanceBelowThreshold,
    RetrievalEmpty,
    SupportDowngraded,
    WorkflowReport,
    WorkflowState,
)

DOWNGRADE_REASON = (
    "The supported answer was downgraded because a cited chunk did not survive validation."
)


def _unique_hits(hits: Sequence[ChunkHit]) -> tuple[tuple[ChunkHit, ...], tuple[int, ...]]:
    """Drop repeated chunk ids, reporting each one that a later hit duplicated."""
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
    """Collapse hits whose whitespace-normalized body repeats, naming the id that kept it."""
    kept: list[ChunkHit] = []
    removed: list[int] = []
    superseded_by: list[int] = []
    owner_by_text: dict[str, int] = {}
    for hit in hits:
        body = " ".join(hit.body.split())
        owner = owner_by_text.get(body)
        if owner is not None:
            removed.append(hit.chunk_id)
            superseded_by.append(owner)
            continue
        owner_by_text[body] = hit.chunk_id
        kept.append(hit)
    return tuple(kept), tuple(removed), tuple(superseded_by)


def _document_preference(
    hits: tuple[ChunkHit, ...],
    max_hits_per_document: int,
) -> tuple[ChunkHit, ...]:
    """Reorder hits so each document's first allowed share is considered before its rest.

    The quota is a preference rather than a filter. Applied as a filter it becomes a
    hard ceiling of ``max_hits_per_document * distinct documents``, so a question a
    single filing answers is capped below ``k`` no matter how much the request is
    widened. Deferring the surplus keeps the diversity benefit when other documents
    can fill the slots and gives them back when nothing else can.
    """
    preferred: list[ChunkHit] = []
    deferred: list[ChunkHit] = []
    taken: dict[str, int] = {}
    for hit in hits:
        used = taken.get(hit.doc_id, 0)
        if used < max_hits_per_document:
            taken[hit.doc_id] = used + 1
            preferred.append(hit)
        else:
            deferred.append(hit)
    return (*preferred, *deferred)


def _fill_slots(
    hits: tuple[ChunkHit, ...],
    *,
    k: int,
    budget_chars: int,
) -> tuple[tuple[ChunkHit, ...], tuple[int, ...]]:
    """Take whole hits in the given order until ``k`` slots or the context budget is spent.

    Selection stops at ``k``, so hits the over-fetch produced but selection never
    reached are not reported as context casualties.
    """
    selected: list[ChunkHit] = []
    dropped: list[int] = []
    used = 0
    for hit in hits:
        if len(selected) == k:
            break
        required = evidence_chars(hit)
        if used + required <= budget_chars:
            selected.append(hit)
            used += required
        else:
            dropped.append(hit.chunk_id)
    return tuple(selected), tuple(dropped)


def select_evidence(
    hits: tuple[ChunkHit, ...],
    *,
    k: int,
    max_hits_per_document: int,
    max_context_chars: int,
) -> tuple[tuple[ChunkHit, ...], tuple[int, ...], tuple[int, ...]]:
    """Choose the evidence sent to the model and name what each limit cost.

    Parameters
    ----------
    hits : tuple[ChunkHit, ...]
        Deduplicated candidates in retrieval rank order.
    k : int
        Positive number of evidence slots to fill.
    max_hits_per_document : int
        Preferred share of the slots for any one document.
    max_context_chars : int
        Budget for the serialized evidence payload the prompt sends.

    Returns
    -------
    tuple[tuple[ChunkHit, ...], tuple[int, ...], tuple[int, ...]]
        Selected evidence, ids the document preference cost a slot, and ids that did
        not fit the context budget.

    Notes
    -----
    Slot filling and the context budget are one pass, so a chunk that does not fit
    leaves its slot to the next candidate instead of emptying it. The quota cost is
    measured against the same selection run without the preference, so only hits that
    genuinely lost a slot are reported.
    """
    budget_chars = evidence_budget_chars(max_context_chars)
    natural, _ = _fill_slots(hits, k=k, budget_chars=budget_chars)
    selected, context_dropped = _fill_slots(
        _document_preference(hits, max_hits_per_document),
        k=k,
        budget_chars=budget_chars,
    )
    chosen = {hit.chunk_id for hit in selected}
    quota_dropped = tuple(hit.chunk_id for hit in natural if hit.chunk_id not in chosen)
    return selected, quota_dropped, context_dropped


def retrieve_node(state: WorkflowState, hits: Sequence[ChunkHit]) -> WorkflowState:
    """Select distinct evidence and apply the whole-chunk context limit.

    Parameters
    ----------
    state : WorkflowState
        Immutable pre-retrieval state.
    hits : Sequence[ChunkHit]
        Ranked and potentially over-fetched candidates.

    Returns
    -------
    WorkflowState
        New state with selected evidence and ordered degradation reasons.

    Raises
    ------
    TypeError
        If a candidate is not a ``ChunkHit``.

    Notes
    -----
    Identity deduplication and text deduplication run first and produce
    ``retrieved_hits``; slot filling under the document preference and the context
    budget then produces ``evidence``.
    """
    unique, duplicates = _unique_hits(hits)
    distinct, text_removed, text_owners = _text_unique_hits(unique)
    evidence, over_quota, dropped = select_evidence(
        distinct,
        k=state.k,
        max_hits_per_document=state.max_hits_per_document,
        max_context_chars=state.max_context_chars,
    )
    reasons = list(state.reasons)
    if duplicates:
        reasons.append(DuplicateRetrievedChunks(chunk_ids=duplicates))
    if text_removed:
        reasons.append(
            DuplicateEvidenceText(
                removed_chunk_ids=text_removed,
                superseded_by_chunk_ids=text_owners,
            )
        )
    if over_quota:
        reasons.append(
            DocumentQuotaApplied(
                dropped_chunk_ids=over_quota,
                max_hits_per_document=state.max_hits_per_document,
            )
        )
    if not distinct:
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
            "retrieved_hits": distinct,
            "evidence": evidence,
            "reasons": tuple(reasons),
            "node_path": (*state.node_path, "retrieve"),
        }
    )


def _provider_failure[OutputT: BaseModel](
    node: GradeOrCheckNode,
    result: ProviderResult[OutputT],
) -> ProviderFailure:
    """Translate a refused provider result into the node's typed failure.

    Every detail the typed refusal carries is forwarded, including the validation
    errors a budget-blocked repair would have addressed. Reducing a blocked repair to
    its budget line would report that the run stopped without reporting that the
    output was also unusable.
    """
    if result.status == "ok":
        raise ValueError("failed provider result must contain a recognized typed refusal")
    refusal = result.refusal
    if isinstance(refusal, SchemaRejected):
        details = refusal.errors
    elif isinstance(refusal, BudgetExceeded):
        details = (
            f"{refusal.which}: used={refusal.used} limit={refusal.limit}",
            *refusal.schema_errors,
        )
    elif isinstance(refusal, ProviderRefusal):
        details = (refusal.message,)
    else:
        raise ValueError("failed provider result must contain a recognized typed refusal")
    return ProviderFailure(
        node=node,
        status=result.status,
        attempts=refusal.attempts,
        details=details,
    )


def _refused[OutputT: BaseModel](
    state: WorkflowState,
    node: GradeOrCheckNode,
    result: ProviderResult[OutputT],
) -> WorkflowState:
    """Commit one provider-backed node that returned a typed refusal."""
    failure = _provider_failure(node, result)
    return state.model_copy(
        update={
            "failure": failure,
            "reasons": (*state.reasons, failure),
            "node_path": (*state.node_path, node),
        }
    )


def grade_node(
    state: WorkflowState,
    result: ProviderResult[RelevanceJudgment],
) -> WorkflowState:
    """Keep relevant grades tied to supplied evidence and record omissions.

    Parameters
    ----------
    state : WorkflowState
        Retrieved state whose evidence defines allowed chunk ids.
    result : ProviderResult[RelevanceJudgment]
        Typed grading result or refusal.

    Returns
    -------
    WorkflowState
        New state with relevant ids, degradation reasons, or provider failure.

    Raises
    ------
    TypeError
        If a successful result does not contain ``RelevanceJudgment``.
    """
    if result.status != "ok":
        return _refused(state, "grade", result)
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
            "node_path": (*state.node_path, "grade"),
        }
    )


def check_node(
    state: WorkflowState,
    result: ProviderResult[AnswerDecision],
) -> WorkflowState:
    """Guard a decision against the citations the grader actually accepted.

    Parameters
    ----------
    state : WorkflowState
        Graded state whose relevant ids define allowed citations.
    result : ProviderResult[AnswerDecision]
        Typed answer decision or refusal.

    Returns
    -------
    WorkflowState
        New state with a guarded decision, reasons, or provider failure.

    Raises
    ------
    TypeError
        If a successful result does not contain ``AnswerDecision``.

    Notes
    -----
    A supported decision survives only when every citation it asked for is allowed.
    The answer and rationale justify the citation set as a whole, so keeping them
    against a reduced set would publish a claim whose surviving evidence may not
    contain it, and no check available here can tell whether it still does.
    """
    if result.status != "ok":
        return _refused(state, "check", result)
    if not isinstance(result.parsed, AnswerDecision):
        raise TypeError("check result must contain AnswerDecision")

    decision = result.parsed
    allowed = set(state.relevant_chunk_ids)
    kept = tuple(chunk_id for chunk_id in decision.citation_chunk_ids if chunk_id in allowed)
    removed = tuple(chunk_id for chunk_id in decision.citation_chunk_ids if chunk_id not in allowed)
    reasons = list(state.reasons)
    if removed:
        reasons.append(CitationsFiltered(removed_chunk_ids=removed, kept_chunk_ids=kept))

    if decision.label == "SUPPORTED" and removed:
        reasons.append(
            SupportDowngraded(
                requested_chunk_ids=decision.citation_chunk_ids,
                kept_chunk_ids=kept,
            )
        )
        guarded = AnswerDecision(
            label="NOT_IN_DOCS",
            answer="NOT_IN_DOCS",
            citation_chunk_ids=(),
            reason=DOWNGRADE_REASON,
        )
    else:
        guarded = decision
    return state.model_copy(
        update={
            "decision": guarded,
            "reasons": tuple(reasons),
            "node_path": (*state.node_path, "check"),
        }
    )


def _absence_rationale(state: WorkflowState) -> str:
    """Explain which stage left the run without supported evidence."""
    if not state.retrieved_hits:
        return "No evidence was retrieved for the query."
    if not state.evidence:
        return "Retrieved evidence could not fit within the context budget."
    if not state.relevant_chunk_ids:
        return "No supplied evidence met the relevance threshold."
    return "The guarded decision did not establish supported evidence."


def report_node(state: WorkflowState) -> WorkflowState:
    """Build the final answer from guarded decisions and validated evidence.

    Parameters
    ----------
    state : WorkflowState
        Checked state containing evidence, decision, and degradation history.

    Returns
    -------
    WorkflowState
        New terminal state containing one strict ``WorkflowReport``.

    Raises
    ------
    ValueError
        If a supported decision cites a chunk that is not in the state's evidence.

    Notes
    -----
    Missing or downgraded support produces ``NOT_IN_DOCS`` and never exposes an
    unvalidated citation. ``check_node`` already removes citations outside the graded
    evidence, so the check here names a broken caller rather than a bad completion.
    """
    evidence_by_id = {hit.chunk_id: hit for hit in state.evidence}
    if state.decision is not None and state.decision.label == "SUPPORTED":
        unknown = tuple(
            chunk_id
            for chunk_id in state.decision.citation_chunk_ids
            if chunk_id not in evidence_by_id
        )
        if unknown:
            raise ValueError(f"supported decision cites chunks outside the evidence: {unknown}")
        citations = tuple(
            EvidenceCitation(
                chunk_id=hit.chunk_id,
                doc_id=hit.doc_id,
                citation=hit.citation,
                start_char=hit.start_char,
                end_char=hit.end_char,
                source_sha256=hit.source_sha256,
            )
            for hit in (evidence_by_id[chunk_id] for chunk_id in state.decision.citation_chunk_ids)
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
