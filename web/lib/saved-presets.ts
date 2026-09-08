import { readStoredValue, writeStoredValue } from "./storage";
import { DEFAULT_SESSION_PROFILE, resolvedRetrievalProfile, type RetrievalProfile, type ReviewSessionDraft } from "./types";

export interface SavedPreset { id: string; name: string; retrieval: RetrievalProfile; description?: string; builtin?: boolean; updated_at?: string | null }
const KEY = "docreview:retrieval-presets:v1";
export const PRESETS_CHANGED = "docreview:retrieval-presets-changed";

/** Validate the same retrieval combinations accepted by conversation requests. */
export function retrievalError(p: RetrievalProfile): string | null {
  if (!p || !["hybrid", "vector", "lexical"].includes(p.strategy)) return "Choose a valid search strategy.";
  if (!Number.isInteger(p.k) || p.k < 1 || p.k > 100 || !Number.isInteger(p.candidate_k) || p.candidate_k < p.k || p.candidate_k > 500) return "Use 1–100 results and at least as many candidates (maximum 500).";
  if (!Number.isInteger(p.rrf_k) || p.rrf_k < 1 || p.rrf_k > 10000) return "RRF k must be an integer from 1 to 10000.";
  if (!Number.isFinite(p.bm25_k1) || p.bm25_k1 <= 0 || !Number.isFinite(p.bm25_b) || p.bm25_b < 0 || p.bm25_b > 1 || !["lucene", "robertson"].includes(p.bm25_idf)) return "Use positive BM25 k1 and BM25 b between 0 and 1.";
  if (typeof p.route_by_language !== "boolean" || ![null, "cross_encoder"].includes(p.reranker ?? null)) return "Choose valid routing and reranker settings.";
  if (p.strategy === "vector" ? p.lexical_ranker !== null : !["ts_rank_cd", "bm25"].includes(p.lexical_ranker ?? "")) return "Vector search has no lexical ranker; other strategies require one.";
  if (p.strategy !== "hybrid" && (p.route_by_language || p.reranker != null)) return "Language routing and reranking require hybrid search.";
  return null;
}

/** Keep hidden invalid settings from being sent after closing the editor. */
export function conversationSettingsError(profile: ReviewSessionDraft): string | null {
  const retrieval = retrievalError(resolvedRetrievalProfile(profile));
  if (retrieval) return retrieval;
  const p = profile.prompt_policy;
  const b = p.workflow_budget;
  const fields = [[p.history_turns, 0, 6], [p.max_context_chars, 1000, 100000], [p.evidence_overfetch, 1, 10], [p.max_hits_per_document, 1, 100], [b.max_iterations, 0, 20], [b.max_input_tokens, 0, 100000], [b.max_output_tokens, 0, 4000]];
  if (fields.some(([value, min, max]) => !Number.isInteger(value) || value < min || value > max)) return "Use whole numbers within the displayed evidence and run-limit ranges.";
  if (!Number.isFinite(b.max_wall_clock_s) || b.max_wall_clock_s < 1 || b.max_wall_clock_s > 600) return "Run time must be between 1 and 600 seconds.";
  if (p.additional_instructions.length > 8000) return "Additional instructions must be at most 8000 characters.";
  return null;
}

/** Compare values independently of property order; names never enter the API contract. */
export function sameRetrieval(a: RetrievalProfile, b: RetrievalProfile): boolean {
  return Object.keys(resolvedRetrievalProfile(DEFAULT_SESSION_PROFILE)).every(key => a[key as keyof RetrievalProfile] === b[key as keyof RetrievalProfile]);
}

/** Read only valid named presets; malformed storage is reported by the caller. */
export function loadSavedPresets(): SavedPreset[] {
  if (typeof window === "undefined") return [];
  const value: unknown = JSON.parse(readStoredValue(KEY) ?? "[]");
  if (!Array.isArray(value) || value.some(p => presetError(p))) throw new Error("Saved presets could not be read.");
  return value;
}

/** Read the latest store before updating one preset, preserving other saved entries. */
export function savePreset(preset: SavedPreset): void {
  const error = presetError(preset);
  if (error) throw new Error(error);
  const entries = loadSavedPresets();
  const name = preset.name.trim();
  if (!name || name.length > 80) throw new Error("Use a preset name of 1–80 characters.");
  if (entries.some(p => p.id !== preset.id && p.name.toLocaleLowerCase() === name.toLocaleLowerCase())) throw new Error("A preset with this name already exists.");
  const saved = { ...preset, name };
  writeStoredValue(KEY, JSON.stringify(entries.some(p => p.id === preset.id) ? entries.map(p => p.id === preset.id ? saved : p) : [...entries, saved]));
  window.dispatchEvent(new Event(PRESETS_CHANGED));
}

/** Validate portable JSON without coercion or silently discarding unknown fields. */
export function presetError(value: unknown): string | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "Enter a preset JSON object.";
  const p = value as SavedPreset;
  if (Object.keys(p).some(key => !["id", "name", "description", "retrieval", "builtin", "updated_at"].includes(key))) return "Unknown preset field.";
  if (typeof p.id !== "string" || !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$/.test(p.id)) return "Use a valid preset ID.";
  if (typeof p.name !== "string" || !p.name.trim() || p.name.length > 80) return "Use a preset name of 1–80 characters.";
  if (p.description !== undefined && (typeof p.description !== "string" || p.description.length > 2000)) return "Description must be at most 2000 characters.";
  if (p.builtin !== undefined && typeof p.builtin !== "boolean") return "Built-in must be a boolean.";
  if (p.updated_at != null && typeof p.updated_at !== "string") return "Updated time must be text.";
  if (!!p.builtin !== ["balanced", "korean", "accuracy"].includes(p.id)) return "Built-in preset identities are reserved.";
  const keys = Object.keys(resolvedRetrievalProfile(DEFAULT_SESSION_PROFILE));
  if (!p.retrieval || typeof p.retrieval !== "object" || Array.isArray(p.retrieval) || Object.keys(p.retrieval).some(key => !keys.includes(key)) || keys.some(key => !(key in p.retrieval))) return "Include all retrieval fields and no unknown fields.";
  return retrievalError(p.retrieval);
}

/** Parse direct edits and imports through the same contract as the form. */
export function parsePresetJSON(text: string): SavedPreset {
  let value: unknown;
  try { value = JSON.parse(text); } catch { throw new Error("Enter valid JSON."); }
  const error = presetError(value);
  if (error) throw new Error(error);
  return value as SavedPreset;
}

/** Delete only one browser preset, preserving the latest state of other tabs. */
export function deletePreset(id: string): void {
  if (["balanced", "korean", "accuracy"].includes(id)) throw new Error("Built-in presets can only be copied.");
  writeStoredValue(KEY, JSON.stringify(loadSavedPresets().filter(p => p.id !== id)));
  window.dispatchEvent(new Event(PRESETS_CHANGED));
}
