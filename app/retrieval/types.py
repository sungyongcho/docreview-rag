"""Shared value objects and deterministic ordering for retrieval results."""

from collections.abc import Iterable
import math
from numbers import Real
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr
from pydantic.functional_validators import field_validator, model_validator

ChunkKind = Literal["text", "table"]

ChunkId = Annotated[StrictInt, Field(gt=0)]
DocId = Annotated[StrictStr, Field(min_length=1, max_length=32)]
Ticker = Annotated[StrictStr, Field(min_length=1, max_length=16)]
FiscalYear = Annotated[StrictInt, Field(gt=0)]
Form = Annotated[StrictStr, Field(min_length=1, max_length=16)]
Item = Annotated[StrictStr, Field(min_length=1, max_length=8)]
SourceSha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
Score = Annotated[StrictFloat, Field(allow_inf_nan=False)]


class ChunkHit(BaseModel):
    """One scored database chunk with human and machine citation data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: ChunkId
    doc_id: DocId
    item: Item | None
    kind: ChunkKind
    citation: Annotated[StrictStr, Field(min_length=1)]
    start_char: Annotated[StrictInt, Field(ge=0)]
    end_char: Annotated[StrictInt, Field(gt=0)]
    source_sha256: SourceSha256
    body: Annotated[StrictStr, Field(min_length=1)]
    context_header: StrictStr
    index_text: Annotated[StrictStr, Field(min_length=1)]
    score: Score

    @model_validator(mode="after")
    def validate_source_and_index_text(self) -> Self:
        """Reject invalid spans and indexed text detached from its evidence."""
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")

        expected = f"{self.context_header}\n\n{self.body}" if self.context_header else self.body
        if self.index_text != expected:
            raise ValueError("index_text must equal context_header plus body")
        return self


class RetrievalFilters(BaseModel):
    """Optional exact-match restrictions shared by every retrieval strategy.

    Values within a field are alternatives, while populated fields are combined.
    Empty tuples mean that the corresponding database dimension is unrestricted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_ids: tuple[DocId, ...] = ()
    tickers: tuple[Ticker, ...] = ()
    fiscal_years: tuple[FiscalYear, ...] = ()
    forms: tuple[Form, ...] = ()
    items: tuple[Item | None, ...] = ()
    kinds: tuple[ChunkKind, ...] = ()

    @field_validator("doc_ids", "tickers", "forms", mode="after")
    @classmethod
    def canonicalize_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Remove duplicates and make equivalent string filters serialize equally."""
        return tuple(sorted(set(values)))

    @field_validator("fiscal_years", mode="after")
    @classmethod
    def canonicalize_years(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        """Remove duplicate years and store them in ascending order."""
        return tuple(sorted(set(values)))

    @field_validator("items", mode="after")
    @classmethod
    def canonicalize_items(cls, values: tuple[str | None, ...]) -> tuple[str | None, ...]:
        """Canonicalize Item filters while retaining support for unnumbered sections."""
        return tuple(sorted(set(values), key=lambda item: (item is not None, item or "")))

    @field_validator("kinds", mode="after")
    @classmethod
    def canonicalize_kinds(cls, values: tuple[ChunkKind, ...]) -> tuple[ChunkKind, ...]:
        """Canonicalize kinds in the schema's text-then-table order."""
        order = {"text": 0, "table": 1}
        return tuple(sorted(set(values), key=order.__getitem__))


def finite_float(value: object, *, nonnumeric: str, nonfinite: str) -> float:
    """Return ``value`` as a finite float or raise with a caller-supplied message.

    Every retrieval boundary that accepts numbers from a provider or a caller
    enforces the same contract: booleans are rejected, the value must be a real
    number, and the materialized float must be finite. This helper owns that
    loop body so each boundary keeps only its own message wording.

    Parameters
    ----------
    value : object
        Candidate numeric value from a provider or caller.
    nonnumeric : str
        Error message raised for booleans and non-``Real`` values.
    nonfinite : str
        Error message raised for NaN and infinite values.

    Returns
    -------
    float
        The validated value materialized as a built-in float.

    Raises
    ------
    ValueError
        If the value violates the numeric-type or finiteness contract.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(nonnumeric)
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(nonfinite)
    return number


def hit_order_key_for_score(hit: ChunkHit, score: float) -> tuple[float, str, str, int, int, int]:
    """Return the shared hit order with a validated replacement score.

    Parameters
    ----------
    hit : ChunkHit
        Evidence-bearing hit whose stable identity breaks score ties.
    score : float
        Validated score that replaces ``hit.score`` for ordering.

    Returns
    -------
    tuple[float, str, str, int, int, int]
        Ascending key that places the replacement score first.
    """
    return (
        -score,
        hit.doc_id,
        hit.source_sha256,
        hit.start_char,
        hit.end_char,
        hit.chunk_id,
    )


def sort_hits(hits: Iterable[ChunkHit]) -> list[ChunkHit]:
    """Return hits in deterministic relevance order without mutating the input.

    Parameters
    ----------
    hits : Iterable[ChunkHit]
        Retrieval hits to order.

    Returns
    -------
    list[ChunkHit]
        A new list ordered by descending score and stable source identity.

    Notes
    -----
    Higher scores sort first. Equal scores use the stable source citation identity,
    followed by the database chunk id as a final unique tie-breaker.
    """
    return sorted(hits, key=lambda hit: hit_order_key_for_score(hit, hit.score))
