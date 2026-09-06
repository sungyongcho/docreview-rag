"""Signed retrieval snapshots and fail-closed per-question evidence selection."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Callable, Sequence
import hashlib
import hmac
import json
import time
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt
from pydantic.functional_validators import model_validator

from app.api.review_profile import ResolvedRetrievalProfile
from app.retrieval.types import ChunkHit, RetrievalFilters

Clock = Callable[[], float]


class EvidenceSnapshotError(ValueError):
    """One stable client-visible snapshot or selection failure."""

    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class StrictEvidenceModel(BaseModel):
    """Frozen strict base for signed evidence values."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SnapshotCandidate(StrictEvidenceModel):
    """One candidate identity protected by a source-content hash."""

    chunk_id: Annotated[StrictInt, Field(gt=0)]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    score: float | None = None


class CandidateSnapshot(StrictEvidenceModel):
    """Canonical payload covered by the server's HMAC signature."""

    version: int = 1
    issued_at: Annotated[StrictInt, Field(ge=0)]
    expires_at: Annotated[StrictInt, Field(gt=0)]
    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    filters_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidates: tuple[SnapshotCandidate, ...]
    routing_queries: dict[str, str] | None = None

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        """Require a future expiry and unique ordered candidate identities."""
        if self.expires_at <= self.issued_at:
            raise ValueError("snapshot expiry must be after issue time")
        ids = tuple(candidate.chunk_id for candidate in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("snapshot candidates must be unique")
        return self


class EvidenceSelection(StrictEvidenceModel):
    """One user selection tied to a server-issued candidate snapshot."""

    candidate_token: str = Field(min_length=1)
    pinned_chunk_ids: tuple[Annotated[StrictInt, Field(gt=0)], ...] = ()
    excluded_chunk_ids: tuple[Annotated[StrictInt, Field(gt=0)], ...] = ()

    @model_validator(mode="after")
    def validate_sets(self) -> Self:
        """Reject duplicate and overlapping pin/exclude declarations."""
        if len(self.pinned_chunk_ids) != len(set(self.pinned_chunk_ids)):
            raise ValueError("pinned chunk ids must be unique")
        if len(self.excluded_chunk_ids) != len(set(self.excluded_chunk_ids)):
            raise ValueError("excluded chunk ids must be unique")
        if set(self.pinned_chunk_ids) & set(self.excluded_chunk_ids):
            raise ValueError("a chunk cannot be both pinned and excluded")
        return self


def _canonical_json(value: object) -> bytes:
    """Serialize one signing value without whitespace or key-order ambiguity."""
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    """Return the canonical JSON SHA-256 for one request-bound value."""
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _b64encode(value: bytes) -> str:
    """Return unpadded URL-safe base64 text."""
    return urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    """Decode unpadded URL-safe base64 text or raise a typed snapshot error."""
    try:
        return urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as error:
        raise EvidenceSnapshotError(
            "candidate_snapshot_invalid",
            "candidate snapshot is not valid base64",
            status_code=422,
        ) from error


class CandidateSnapshotCodec:
    """Issue and verify short-lived, stateless evidence candidate snapshots."""

    def __init__(
        self,
        secret: bytes,
        *,
        ttl_seconds: int = 30 * 60,
        clock: Clock = time.time,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("candidate signing secret must be at least 32 bytes")
        if ttl_seconds <= 0:
            raise ValueError("candidate snapshot TTL must be positive")
        self._secret = secret
        self._ttl_seconds = ttl_seconds
        self._clock = clock

    def issue(
        self,
        *,
        query: str,
        profile: ResolvedRetrievalProfile,
        filters: RetrievalFilters,
        candidates: Sequence[ChunkHit],
        routing_queries: dict[str, str] | None = None,
    ) -> tuple[str, CandidateSnapshot]:
        """Return an opaque token and its non-secret validated payload."""
        issued_at = int(self._clock())
        snapshot = CandidateSnapshot(
            issued_at=issued_at,
            expires_at=issued_at + self._ttl_seconds,
            query_sha256=_sha256(query),
            profile_sha256=_sha256(profile.model_dump(mode="json")),
            filters_sha256=_sha256(filters.model_dump(mode="json")),
            routing_queries=routing_queries,
            candidates=tuple(
                SnapshotCandidate(
                    chunk_id=hit.chunk_id, source_sha256=hit.source_sha256, score=hit.score
                )
                for hit in candidates
            ),
        )
        payload = _canonical_json(snapshot.model_dump(mode="json"))
        signature = hmac.digest(self._secret, payload, "sha256")
        return f"{_b64encode(payload)}.{_b64encode(signature)}", snapshot

    def verify(
        self,
        token: str,
        *,
        query: str,
        profile: ResolvedRetrievalProfile,
        filters: RetrievalFilters,
    ) -> CandidateSnapshot:
        """Verify signature, expiry, and retrieval request binding."""
        try:
            payload_text, signature_text = token.split(".", 1)
        except ValueError as error:
            raise EvidenceSnapshotError(
                "candidate_snapshot_invalid",
                "candidate snapshot has an invalid shape",
                status_code=422,
            ) from error
        payload = _b64decode(payload_text)
        signature = _b64decode(signature_text)
        expected = hmac.digest(self._secret, payload, "sha256")
        if not hmac.compare_digest(signature, expected):
            raise EvidenceSnapshotError(
                "candidate_snapshot_invalid",
                "candidate snapshot signature is invalid",
                status_code=422,
            )
        try:
            snapshot = CandidateSnapshot.model_validate_json(payload)
        except Exception as error:
            raise EvidenceSnapshotError(
                "candidate_snapshot_invalid",
                "candidate snapshot payload is invalid",
                status_code=422,
            ) from error
        if int(self._clock()) >= snapshot.expires_at:
            raise EvidenceSnapshotError(
                "candidate_snapshot_expired",
                "candidate snapshot expired; retrieve evidence again",
                status_code=409,
            )
        expected_bindings = (
            (_sha256(query), snapshot.query_sha256),
            (_sha256(profile.model_dump(mode="json")), snapshot.profile_sha256),
            (_sha256(filters.model_dump(mode="json")), snapshot.filters_sha256),
        )
        if any(not hmac.compare_digest(actual, recorded) for actual, recorded in expected_bindings):
            raise EvidenceSnapshotError(
                "candidate_snapshot_mismatch",
                "candidate snapshot does not match this query and retrieval profile",
                status_code=422,
            )
        return snapshot


def select_evidence(
    snapshot: CandidateSnapshot,
    selection: EvidenceSelection,
    candidates: Sequence[ChunkHit],
    *,
    k: int,
    max_context_chars: int,
) -> tuple[ChunkHit, ...]:
    """Validate membership and return pinned-first evidence with ranked fill."""
    if len(selection.pinned_chunk_ids) > k:
        raise EvidenceSnapshotError(
            "too_many_pinned_candidates",
            "pinned evidence cannot exceed the answer evidence limit",
            status_code=422,
        )
    by_id = {candidate.chunk_id: candidate for candidate in candidates}
    snapshot_by_id = {candidate.chunk_id: candidate for candidate in snapshot.candidates}
    requested = set(selection.pinned_chunk_ids) | set(selection.excluded_chunk_ids)
    if outside := sorted(requested - set(snapshot_by_id)):
        raise EvidenceSnapshotError(
            "invalid_evidence_selection",
            f"evidence selection contains candidates outside the snapshot: {outside}",
            status_code=422,
        )
    stale = tuple(
        candidate.chunk_id
        for candidate in snapshot.candidates
        if candidate.chunk_id not in by_id
        or by_id[candidate.chunk_id].source_sha256 != candidate.source_sha256
    )
    if stale:
        raise EvidenceSnapshotError(
            "candidate_snapshot_stale",
            "candidate evidence changed; retrieve evidence again",
            status_code=409,
        )
    pinned = tuple(by_id[chunk_id] for chunk_id in selection.pinned_chunk_ids)
    if len({candidate.body for candidate in pinned}) != len(pinned):
        raise EvidenceSnapshotError(
            "duplicate_pinned_evidence",
            "pinned evidence must not duplicate the same source text",
            status_code=422,
        )
    if sum(len(candidate.index_text) for candidate in pinned) > max_context_chars:
        raise EvidenceSnapshotError(
            "pinned_evidence_too_large",
            "pinned evidence exceeds the context budget",
            status_code=422,
        )
    excluded = set(selection.excluded_chunk_ids)
    pinned_ids = set(selection.pinned_chunk_ids)
    ranked_fill = (
        by_id[item.chunk_id]
        for item in snapshot.candidates
        if item.chunk_id not in excluded and item.chunk_id not in pinned_ids
    )
    return (*pinned, *tuple(ranked_fill))[:k]
