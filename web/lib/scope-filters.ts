import type { ReviewSessionDraft } from "./types";

/** The conversation filter fields a company × year selection can scope. */
export type ScopeFilters = Pick<ReviewSessionDraft, "registries" | "issuers" | "fiscal_years">;
