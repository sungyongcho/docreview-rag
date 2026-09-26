"""Resolve issuer selections and each routed request's retrieval scope against the manifest."""

import asyncio
import logging
from pathlib import Path
import re
from typing import cast

from app.api.errors import ApiProblemError
from app.api.review_profile import (
    ResolvedRetrievalProfile,
    ReviewSessionProfile,
    ServerBM25,
    resolve_retrieval_profile,
)
from app.api.scope_diagnostics import manifest_problem
from app.config import get_settings
from app.db.session_factory import SessionFactory
from app.observability.types import JsonObject
from app.operator.jobs import JobStore
from app.retrieval.scope import (
    ManifestScopeIndex,
    QueryScopeError,
    ResolvedQueryScope,
    resolve_query_scope,
)
from app.workflow.gate import CORPUS_WIDE_CUES


class ScopeResolver:
    """Resolve selections and retrieval scope against the corpus manifest's scope index.

    The index is injected or loaded lazily from ``manifest.json`` under the corpus root
    and reloaded whenever that file changes, so every stage of a request reads the
    identities the manifest currently declares.

    Parameters
    ----------
    corpus_root : Path | None
        Corpus directory holding ``manifest.json``; ``None`` reads the configured one.
    scope_index : ManifestScopeIndex | None
        Index to serve until the manifest file is first observed; ``None`` loads it.
    session_factory : SessionFactory
        Session boundary used only to attach recent corpus-job context to a failure.
    bm25 : ServerBM25
        Server BM25 values that fill what a retrieval plan leaves unstated.
    developer : bool
        Whether a manifest failure carries diagnostic detail and recent job context.
    secret_values : tuple[str, ...]
        Configured secrets redacted from diagnostic detail.
    """

    def __init__(
        self,
        *,
        corpus_root: Path | None,
        scope_index: ManifestScopeIndex | None,
        session_factory: SessionFactory,
        bm25: ServerBM25,
        developer: bool,
        secret_values: tuple[str, ...],
    ) -> None:
        self._corpus_root = corpus_root
        self._scope_index = scope_index
        self._scope_signature: tuple[int, int] | None = None
        self._session_factory = session_factory
        self._bm25 = bm25
        self._developer = developer
        self._secret_values = secret_values

    def manifest_index(self) -> ManifestScopeIndex:
        """Return the injected or lazily loaded manifest scope index, reloading on change."""
        root = (self._corpus_root or get_settings().corpus_dir).resolve()
        path = root / "manifest.json"
        try:
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = None
        if self._scope_index is not None and (signature is None or self._scope_signature is None):
            return self._scope_index
        if self._scope_index is None or signature != self._scope_signature:
            try:
                self._scope_index = ManifestScopeIndex.from_paths((path,))
                self._scope_signature = signature
            except (OSError, ValueError, TypeError) as error:
                logging.getLogger(__name__).error(
                    "Manifest scope index could not be loaded", exc_info=True
                )
                raise manifest_problem(
                    error,
                    root,
                    developer=self._developer,
                    secret_values=self._secret_values,
                ) from error
        return self._scope_index

    async def manifest_index_for_decision(self) -> ManifestScopeIndex:
        """Attach stage-zero attribution and optional recent acquisition context on failure."""
        try:
            return self.manifest_index()
        except ApiProblemError as error:
            job = None
            if self._developer:
                try:
                    jobs = await asyncio.wait_for(
                        JobStore(session_factory=self._session_factory).list(
                            domain="corpus", limit=100
                        ),
                        timeout=0.5,
                    )
                    recent = max(
                        (
                            row
                            for row in jobs
                            if row.kind in {"acquire_edgar", "acquire_dart"}
                            and (
                                row.status in {"queued", "running"}
                                or row.result_refs.get("manifest") == "manifest.json"
                            )
                        ),
                        key=lambda row: (row.status in {"queued", "running"}, row.updated_at),
                        default=None,
                    )
                    if recent is not None:
                        job = {
                            "job_id": recent.job_id,
                            "kind": recent.kind,
                            "status": recent.status,
                        }
                except Exception as job_error:  # noqa: BLE001 - preserve the original manifest failure
                    logging.getLogger(__name__).info(
                        "Recent corpus-job context unavailable (%s)", type(job_error).__name__
                    )
            error.error = error.error.model_copy(update={"failed_stage": "path", "corpus_job": job})
            raise

    def selected_issuers(self, session_profile: ReviewSessionProfile) -> tuple[str, ...]:
        """Resolve selected issuers only from fully known selections."""
        filters = session_profile.explicit_filters()
        index = self.manifest_index()
        selected = {item.issuer for item in index.issuers_named(filters.issuers)}
        doc_ids = set(filters.doc_ids)
        if doc_ids and doc_ids.issubset(index.documents):
            selected.update(index.documents[doc_id].issuer for doc_id in doc_ids)
        return tuple(sorted(selected))

    def _resolved_request(
        self,
        query: str,
        session_profile: ReviewSessionProfile,
    ) -> tuple[ResolvedRetrievalProfile, ResolvedQueryScope]:
        """Resolve the session profile and its explicit query scope."""
        profile = resolve_retrieval_profile(session_profile, self._bm25)
        explicit_filters = session_profile.explicit_filters()
        if session_profile.snapshot_id is not None and explicit_filters.snapshot_id is None:
            explicit_filters = explicit_filters.model_copy(
                update={"snapshot_id": session_profile.snapshot_id}
            )
        try:
            scope = resolve_query_scope(
                query,
                self.manifest_index(),
                corpus_scope=session_profile.corpus_scope,
                explicit_filters=explicit_filters,
            )
        except QueryScopeError as error:
            raise ApiProblemError(
                status_code=422,
                code=error.code,
                message=error.message,
            ) from error
        return profile, scope

    def path_scope(
        self, session_profile: ReviewSessionProfile, path: JsonObject
    ) -> tuple[ResolvedRetrievalProfile, ResolvedQueryScope]:
        """Attach actionable scope failures before retrieval rather than producing NOT_IN_DOCS."""
        query = cast("str", path["retrieval_query"])
        try:
            index = self.manifest_index()
            names = cast("list[str]", path.get("requested_issuers", []))
            targets = [index.named_target(name) for name in names]
            missing = [name for name, matches in zip(names, targets, strict=True) if not matches]
            path["missing_issuers"] = list(missing)
            if missing:
                raise ApiProblemError(
                    status_code=422,
                    code="unknown_issuer",
                    message="No filings are available for: " + ", ".join(missing) + ".",
                )
            if any(len(matches) != 1 for matches in targets):
                raise ApiProblemError(
                    status_code=422,
                    code="ambiguous_issuer",
                    message="Please clarify which company or companies to analyze.",
                )
            selected = self.selected_issuers(session_profile)
            anchored = bool(session_profile.explicit_filters().issuers) or (len(selected) == 1)
            if path.get("target_scope") == "all" and not CORPUS_WIDE_CUES.search(query):
                raise ApiProblemError(
                    status_code=422,
                    code="ambiguous_issuer",
                    message="Please clarify which company or companies to analyze.",
                )
            if path.get("target_scope") == "unclear" or (
                not names
                and path.get("target_scope") != "all"
                and not index.match(query)
                and not anchored
            ):
                raise ApiProblemError(
                    status_code=422,
                    code="ambiguous_issuer",
                    message="Please clarify which company or companies to analyze.",
                )
            effective_profile = session_profile
            if (
                not names
                and not session_profile.issuers
                and not index.match(query)
                and len(selected) == 1
            ):
                effective_profile = session_profile.model_copy(update={"issuers": selected})
            profile, scope = self._resolved_request(query, effective_profile)
            if path.get("target_scope") == "all" and scope.source == "query_language":
                # A confirmed corpus-wide request keeps every corpus language.
                scope = scope.model_copy(
                    update={
                        "source": "explicit",
                        "inferred_languages": (),
                        "filters": scope.filters.model_copy(update={"languages": ()}),
                    }
                )
            # Never silently suppress an explicitly requested target in a pinned selection.
            extracted = tuple(sorted({item.issuer for matches in targets for item in matches}))
            if extracted and not set(extracted).issubset(scope.filters.issuers):
                raise ApiProblemError(
                    status_code=422,
                    code="query_scope_conflict",
                    message="The requested company is outside the selected document scope.",
                )
            if not scope.filters.fiscal_years:
                years = tuple(
                    sorted(
                        {int(year) for year in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", query)}
                    )
                )
                scope = scope.model_copy(
                    update={"filters": scope.filters.model_copy(update={"fiscal_years": years})}
                )
            path["resolved_scope"] = scope.model_dump(mode="json")
            filters = scope.filters
            if session_profile.snapshot_id is None and not any(
                (not filters.registries or doc.registry in filters.registries)
                and (not filters.doc_ids or doc.doc_id in filters.doc_ids)
                and (not filters.issuers or doc.issuer in filters.issuers)
                and (not filters.languages or doc.language in filters.languages)
                and (not filters.fiscal_years or doc.fiscal_year in filters.fiscal_years)
                and (not filters.forms or doc.form in filters.forms)
                for doc in self.manifest_index().documents.values()
            ):
                raise ApiProblemError(
                    status_code=422,
                    code="query_scope_empty",
                    message=(
                        "No corpus documents match the resolved scope. "
                        "Switch scope to Auto or change the issuer/year filters."
                    ),
                )
            return profile, scope
        except ApiProblemError as error:
            if error.error.code in {
                "query_scope_conflict",
                "profile_scope_conflict",
                "query_scope_empty",
                "unknown_issuer",
                "ambiguous_issuer",
            }:
                path["scope_outcome"] = (
                    "empty"
                    if error.error.code in {"query_scope_empty", "unknown_issuer"}
                    else "ambiguous"
                    if error.error.code == "ambiguous_issuer"
                    else "conflict"
                )
                path["stopping_reason"] = error.error.code
                path["stopping_stage"] = "gate"
                path["stopping_message"] = error.error.message
                path["suggested_scope"] = (
                    "auto"
                    if error.error.code in {"query_scope_conflict", "profile_scope_conflict"}
                    else None
                )
                raise ApiProblemError(
                    status_code=error.status_code,
                    code=error.error.code,
                    message=error.error.message,
                    path_decision=path,
                ) from error
            raise
