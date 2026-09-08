import { OPERATION_CATEGORIES, OPERATION_TARGETS, type OperatorCommand, type OperationsFilter, type OperationsTargetFilter, type OperatorTarget } from "./operator-api";
import { browserStorage as rawBrowserStorage, previewState } from "./production-preview";
import type { Conversation, ExperimentDefaults, ReviewSessionDraft } from "./types";
import { DEFAULT_EXPERIMENT_DEFAULTS, DEFAULT_SESSION_PROFILE, DEFAULT_PROFILE } from "./types";

const STORAGE_KEY = "docreview:conversations:v2";
const LEGACY_STORAGE_KEY = "docreview:conversations:v1";
export const ONBOARDING_KEY = "docreview:onboarding:v1";
const DEFAULT_PROFILE_KEY = "docreview:profile-defaults:v1";
const DESKTOP_JOB_NOTIFICATIONS_KEY = "docreview:desktop-job-notifications:v1";
const EXPERIMENT_DEFAULTS_KEY = "docreview:experiment-defaults:v1";
/** Help mode open/closed; separate from the frozen onboarding key so the tour sentinel never changes. */
export const HELP_KEY = "docreview:help:v1";
const OPERATIONS_FILTER_KEY = "docreview:operations-filter:v1";
const OPERATIONS_TARGET_FILTER_KEY = "docreview:operations-target-filter:v1";
const MAX_CONVERSATIONS = 30;
const MAX_MESSAGES = 100;

export function loadConversations(): Conversation[] {
  if (typeof window === "undefined") return [];
  try {
    const current = browserStorage().getItem(STORAGE_KEY);
    const value: unknown = JSON.parse(current ?? browserStorage().getItem(LEGACY_STORAGE_KEY) ?? "[]");
    if (!Array.isArray(value)) return [];
    const migrated = value.filter(isConversation).map(migrateConversation);
    if (productionBrowserStorageEnabled() && current === null && value.length) {
      const raw = JSON.stringify({ version: 2, value: JSON.stringify(migrated) });
      if (preserveCorruptValues() && writeRaw(STORAGE_KEY, raw)) writeRaw(LEGACY_STORAGE_KEY, null);
      else sessionValues.set(STORAGE_KEY, raw);
    }
    return migrated.slice(0, MAX_CONVERSATIONS);
  } catch {
    return [];
  }
}

export function saveConversations(conversations: Conversation[]): Conversation[] {
  const bounded = conversations
    .map((conversation) => ({ ...conversation, messages: conversation.messages.slice(-MAX_MESSAGES) }))
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
    .slice(0, MAX_CONVERSATIONS);
  if (typeof window !== "undefined") {
    browserStorage().setItem(STORAGE_KEY, JSON.stringify(bounded));
  }
  return bounded;
}

export function newConversation(profile: ReviewSessionDraft = loadDefaultProfile()): Conversation {
  const now = new Date().toISOString();
  return {
    id: crypto.randomUUID(),
    title: "New review",
    createdAt: now,
    updatedAt: now,
    messages: [],
    profile,
  };
}

export function loadDefaultProfile(): ReviewSessionDraft {
  if (typeof window === "undefined") return DEFAULT_SESSION_PROFILE;
  try {
    const value = JSON.parse(browserStorage().getItem(DEFAULT_PROFILE_KEY) ?? "null") as Partial<ReviewSessionDraft> | null;
    return value ? mergeProfile(value) : DEFAULT_SESSION_PROFILE;
  } catch {
    return DEFAULT_SESSION_PROFILE;
  }
}

export function saveDefaultProfile(profile: ReviewSessionDraft): void {
  if (typeof window !== "undefined") browserStorage().setItem(DEFAULT_PROFILE_KEY, JSON.stringify(profile));
}

/** Save only the prompt text; other defaults and existing conversations stay intact. */
export function saveDefaultPrompt(additional_instructions: string): void {
  const defaults = loadDefaultProfile();
  saveDefaultProfile({ ...defaults, prompt_policy: { ...defaults.prompt_policy, additional_instructions } });
}

export function resetDefaultProfile(): void {
  if (typeof window !== "undefined") browserStorage().removeItem(DEFAULT_PROFILE_KEY);
}

export function loadExperimentDefaults(): ExperimentDefaults {
  if (typeof window === "undefined") return DEFAULT_EXPERIMENT_DEFAULTS;
  try {
    const value = JSON.parse(browserStorage().getItem(EXPERIMENT_DEFAULTS_KEY) ?? "null") as Partial<ExperimentDefaults> | null;
    if (!value) return DEFAULT_EXPERIMENT_DEFAULTS;
    const suiteId = ["sec-en", "sec-ko", "dart-en", "dart-ko", "sec-en_v2_astra", "sec-ko_v2_astra", "sec-mixed_v2_astra"].includes(String(value.suite_id))
      ? value.suite_id as ExperimentDefaults["suite_id"]
      : DEFAULT_EXPERIMENT_DEFAULTS.suite_id;
    const mode = value.mode === "matrix" || value.mode === "quick"
      ? value.mode
      : DEFAULT_EXPERIMENT_DEFAULTS.mode;
    const normalized = { suite_id: suiteId, mode, golden_revision_id: positiveId(value.golden_revision_id) };
    if (Object.keys(value).some(key => !["suite_id", "mode", "golden_revision_id"].includes(key))) {
      try { browserStorage().setItem(EXPERIMENT_DEFAULTS_KEY, JSON.stringify(normalized)); }
      catch (error) { if (!(error instanceof DOMException)) throw error; }
    }
    return normalized;
  } catch {
    return DEFAULT_EXPERIMENT_DEFAULTS;
  }
}

export function saveExperimentDefaults(value: ExperimentDefaults): void {
  if (typeof window !== "undefined") browserStorage().setItem(EXPERIMENT_DEFAULTS_KEY, JSON.stringify({ suite_id: value.suite_id, mode: value.mode, golden_revision_id: value.golden_revision_id }));
}

export function resetExperimentDefaults(): void {
  if (typeof window !== "undefined") browserStorage().removeItem(EXPERIMENT_DEFAULTS_KEY);
}

export function desktopJobNotificationsEnabled(): boolean {
  return typeof window !== "undefined"
    && browserStorage().getItem(DESKTOP_JOB_NOTIFICATIONS_KEY) === "enabled";
}

export function setDesktopJobNotifications(enabled: boolean): void {
  if (typeof window === "undefined") return;
  if (enabled) browserStorage().setItem(DESKTOP_JOB_NOTIFICATIONS_KEY, "enabled");
  else browserStorage().removeItem(DESKTOP_JOB_NOTIFICATIONS_KEY);
}

export function loadHelpOpen(): boolean {
  return typeof window !== "undefined" && browserStorage().getItem(HELP_KEY) === "open";
}

export function saveHelpOpen(open: boolean): void {
  if (typeof window === "undefined") return;
  if (open) browserStorage().setItem(HELP_KEY, "open");
  else browserStorage().removeItem(HELP_KEY);
}

export function browserStorageUsage(): number {
  if (productionBrowserStorageEnabled()) return browserStorageBreakdown().reduce((total, row) => total + row.bytes, 0);
  // Count only application-owned keys; browser and third-party data stay outside this view.
  if (typeof window === "undefined") return 0;
  let bytes = 0;
  for (let index = 0; index < browserStorage().length; index += 1) {
    const key = browserStorage().key(index);
    if (!key?.startsWith("docreview:")) continue;
    bytes += new TextEncoder().encode(key + (browserStorage().getItem(key) ?? "")).byteLength;
  }
  return bytes;
}


function mergeProfile(profile: Partial<ReviewSessionDraft>): ReviewSessionDraft {
  return {
    ...DEFAULT_SESSION_PROFILE,
    ...profile,
    prompt_policy: {
      ...DEFAULT_SESSION_PROFILE.prompt_policy,
      ...(profile.prompt_policy ?? {}),
      workflow_budget: {
        ...DEFAULT_SESSION_PROFILE.prompt_policy.workflow_budget,
        ...(profile.prompt_policy?.workflow_budget ?? {}),
      },
    },
  };
}

function positiveId(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
}

function migrateConversation(conversation: Conversation): Conversation {
  const profile = conversation.profile as unknown as Record<string, unknown> | null;
  if (profile && "engine" in profile) {
    return {
      ...conversation,
      profile: mergeProfile(profile as Partial<ReviewSessionDraft>),
    };
  }
  return {
    ...conversation,
    profile: profile
      ? { ...DEFAULT_SESSION_PROFILE, retrieval_preset: "custom", custom_retrieval: profile as unknown as import("./types").RetrievalProfile }
      : DEFAULT_SESSION_PROFILE,
  };
}

function isConversation(value: unknown): value is Conversation {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<Conversation>;
  return (
    typeof item.id === "string" &&
    typeof item.title === "string" &&
    typeof item.createdAt === "string" &&
    typeof item.updatedAt === "string" &&
    Array.isArray(item.messages)
  );
}

/** Category filter last chosen on System › Operations; unknown or missing values fall back to `all`. */
export function loadOperationsFilter(): OperationsFilter {
  if (typeof window === "undefined") return "all";
  const value = browserStorage().getItem(OPERATIONS_FILTER_KEY);
  return OPERATION_CATEGORIES.includes(value as OperatorCommand["category"]) ? (value as OperationsFilter) : "all";
}

export function saveOperationsFilter(filter: OperationsFilter): void {
  if (typeof window === "undefined") return;
  if (filter === "all") browserStorage().removeItem(OPERATIONS_FILTER_KEY);
  else browserStorage().setItem(OPERATIONS_FILTER_KEY, filter);
}


/** Remember a target independently of the category; stale values leave every target visible. */
export function loadOperationsTargetFilter(): OperationsTargetFilter {
  if (typeof window === "undefined") return "all";
  const value = browserStorage().getItem(OPERATIONS_TARGET_FILTER_KEY);
  return OPERATION_TARGETS.includes(value as OperatorTarget) ? value as OperationsTargetFilter : "all";
}

/** Persist this browser's target choice without changing command execution or category selection. */
export function saveOperationsTargetFilter(filter: OperationsTargetFilter): void {
  if (typeof window === "undefined") return;
  if (filter === "all") browserStorage().removeItem(OPERATIONS_TARGET_FILTER_KEY);
  else browserStorage().setItem(OPERATIONS_TARGET_FILTER_KEY, filter);
}

export const STORAGE_NOTICE_KEY = "docreview:storage-notice:v1";
const ACTIVE_CONVERSATION_KEY = "docreview:active-conversation:v1";
const RECOVERY_KEY = "docreview:storage-recovery:v1";
const STORAGE_WARNING_EVENT = "docreview:storage-warning";
const STORAGE_CHANGED_EVENT = "docreview:storage-restored";
export const STORAGE_WARNING_BYTES = 4 * 1024 * 1024;
let storageEnvironment: "dev" | "prod" | undefined;
const sessionValues = new Map<string, string | null>();
const knownValues = new Map<string, string | null>();
const corruptValues = new Map<string, string>();
const warnings = new Map<string, StorageWarning>();
export interface StorageWarning { reason: "quota" | "unavailable" | "corrupt" | "version"; key: string; }
interface StoredValue { version: number; value: string; }
export interface BrowserStorageExport { format: "docreview-browser-storage"; version: 1; entries: Array<{ key: string; version: number; value: string }>; }

/** Enable migrations only after the real server identifies this page as production. */
export function configureBrowserStorage(environment?: "dev" | "prod"): void {
  if (storageEnvironment === environment) return;
  if (storageEnvironment !== environment) {
    sessionValues.clear(); knownValues.clear(); corruptValues.clear(); warnings.clear();
  }
  storageEnvironment = environment;
  if (typeof window !== "undefined" && productionBrowserStorageEnabled()) {
    for (const [key] of storedEntries()) if (key !== RECOVERY_KEY) readProductionValue(key);
    window.dispatchEvent(new Event(STORAGE_CHANGED_EVENT));
  }
}

/** Preview sessions always retain their existing isolated memory storage. */
export function productionBrowserStorageEnabled(): boolean {
  return storageEnvironment === "prod" && previewState().mode === "normal";
}

/** Record only one warning per cause; never include user payloads in notifications. */
function storageWarning(reason: StorageWarning["reason"], key: string): void {
  if (warnings.has(reason)) return;
  const warning = { reason, key }; warnings.set(reason, warning);
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(STORAGE_WARNING_EVENT, { detail: warning }));
}

/** Replay initialization warnings after the notification region mounts. */
export function subscribeStorageWarnings(listener: (warning: StorageWarning) => void): () => void {
  for (const warning of warnings.values()) listener(warning);
  const changed = (event: Event) => listener((event as CustomEvent<StorageWarning>).detail);
  window.addEventListener(STORAGE_WARNING_EVENT, changed);
  return () => window.removeEventListener(STORAGE_WARNING_EVENT, changed);
}

/** Match only this application's browser keys, including its legacy locale spelling. */
function ownedStorageKey(key: string): boolean { return key.startsWith("docreview:") || key === "docreview.locale"; }

/** Keep current versioned keys; migrate only the previous unversioned preference names. */
function versionedKey(key: string): string {
  if (key === "docreview.locale") return "docreview:locale:v1";
  return /:v\d+$/.test(key) ? key : `${key}:v1`;
}

/** The key names the concern's schema version; no guessed migration of future versions. */
function keyVersion(key: string): number { return Number(key.match(/:v(\d+)$/)?.[1] ?? 0); }

/** Validate JSON objects without trusting their prototype or an array as a profile. */
function objectValue(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }

/** Validate known retrieval scalar types before preset editors consume imported values. */
function validRetrieval(value: unknown): boolean {
  if (!objectValue(value)) return false;
  for (const [key, initial] of Object.entries(DEFAULT_PROFILE)) {
    const actual = value[key];
    if (actual === undefined || key === "lexical_ranker" && actual === null) continue;
    if (initial !== null && (typeof actual !== typeof initial || typeof actual === "number" && !Number.isFinite(actual))) return false;
  }
  if (value.reranker !== undefined && value.reranker !== null && value.reranker !== "cross_encoder") return false;
  if (value.lexical_ranker !== undefined && value.lexical_ranker !== null && !["ts_rank_cd", "bm25"].includes(String(value.lexical_ranker))) return false;
  if (value.strategy !== undefined && !["hybrid", "vector", "lexical"].includes(String(value.strategy))) return false;
  if (value.bm25_idf !== undefined && !["lucene", "robertson"].includes(String(value.bm25_idf))) return false;
  return true;
}

/** Reject malformed nested settings before they can enter a React render or request. */
function validProfile(value: unknown): boolean {
  if (!objectValue(value)) return false;
  for (const field of ["doc_ids", "registries", "issuers", "sections", "forms", "languages", "kinds", "fiscal_years"]) {
    const values = value[field];
    if (values !== undefined && (!Array.isArray(values) || values.some(item => field === "fiscal_years" ? typeof item !== "number" || !Number.isInteger(item) : (field !== "sections" || item !== null) && typeof item !== "string"))) return false;
  }
  if (value.local_model !== undefined && value.local_model !== null && typeof value.local_model !== "string") return false;
  if (value.snapshot_id !== undefined && value.snapshot_id !== null && (typeof value.snapshot_id !== "number" || !Number.isInteger(value.snapshot_id))) return false;
  if (value.custom_retrieval !== undefined && value.custom_retrieval !== null && !validRetrieval(value.custom_retrieval)) return false;
  if (value.corpus_scope !== undefined && !["auto", "sec", "dart"].includes(String(value.corpus_scope))) return false;
  if (value.retrieval_preset !== undefined && !["balanced", "korean", "accuracy", "custom"].includes(String(value.retrieval_preset))) return false;
  if (value.engine !== undefined && !["openai", "local"].includes(String(value.engine))) return false;
  for (const field of ["prompt_policy", "custom_retrieval", "filters"]) {
    if (value[field] !== undefined && value[field] !== null && !objectValue(value[field])) return false;
  }
  const policy = value.prompt_policy;
  if (objectValue(policy)) {
    for (const field of ["history_turns", "max_context_chars", "evidence_overfetch", "max_hits_per_document"]) if (policy[field] !== undefined && (typeof policy[field] !== "number" || !Number.isFinite(policy[field]))) return false;
    if (policy.additional_instructions !== undefined && typeof policy.additional_instructions !== "string") return false;
    if (policy.workflow_budget !== undefined && !objectValue(policy.workflow_budget)) return false;
    if (objectValue(policy.workflow_budget) && Object.values(policy.workflow_budget).some(v => typeof v !== "number" || !Number.isFinite(v))) return false;
  }
  return true;
}

/** Validate the stored concerns while leaving future registered JSON concerns readable. */
function validStoredValue(key: string, raw: string): boolean {
  if (/docreview:(?:theme|locale):v1$/.test(key)) return key.includes(":theme:") ? ["light", "dark", "system"].includes(raw) : ["en", "ko"].includes(raw);
  if (/docreview:layout:/.test(key)) return Number.isFinite(Number(raw)) && Number(raw) > 0;
  if ([ONBOARDING_KEY, STORAGE_NOTICE_KEY].includes(key)) return raw === "done";
  if (key === HELP_KEY) return raw === "open";
  if (key === DESKTOP_JOB_NOTIFICATIONS_KEY) return raw === "enabled";
  if (key === ACTIVE_CONVERSATION_KEY) return raw.length > 0;
  if (key === OPERATIONS_FILTER_KEY) return raw === "all" || OPERATION_CATEGORIES.includes(raw as OperatorCommand["category"]);
  if (key === OPERATIONS_TARGET_FILTER_KEY) return raw === "all" || OPERATION_TARGETS.includes(raw as OperatorTarget);
  try {
    const value: unknown = JSON.parse(raw);
    if (key === STORAGE_KEY || key === LEGACY_STORAGE_KEY) return Array.isArray(value) && value.every(v => isConversation(v)
      && (v.profile == null || validProfile(v.profile)) && v.messages.every(message => objectValue(message) && typeof message.id === "string" && typeof message.text === "string" && ["user", "assistant"].includes(String(message.role))));
    if (key === DEFAULT_PROFILE_KEY) return validProfile(value);
    if (key === "docreview:retrieval-presets:v1") return Array.isArray(value) && value.every(item => objectValue(item) && typeof item.id === "string" && typeof item.name === "string" && validRetrieval(item.retrieval));
    if (key === EXPERIMENT_DEFAULTS_KEY || key === RECOVERY_KEY) return objectValue(value);
    return value !== null && typeof value === "object";
  } catch { return false; }
}

/** Keep a session overlay when persistence is unavailable or a removal cannot reach disk. */
function readRaw(key: string): string | null {
  if (sessionValues.has(key)) return sessionValues.get(key) ?? null;
  try { const value = rawBrowserStorage().getItem(key); knownValues.set(key, value); return value; }
  catch { storageWarning("unavailable", key); return knownValues.get(key) ?? null; }
}

/** Distinguish quota exhaustion from blocked storage without exposing exception payloads. */
function writeRaw(key: string, value: string | null): boolean {
  sessionValues.set(key, value);
  try {
    if (value === null) rawBrowserStorage().removeItem(key); else rawBrowserStorage().setItem(key, value);
    knownValues.set(key, value); sessionValues.delete(key);
    return true;
  } catch (error) {
    storageWarning(error instanceof DOMException && ["QuotaExceededError", "NS_ERROR_DOM_QUOTA_REACHED"].includes(error.name) ? "quota" : "unavailable", key);
    return false;
  }
}

/** Retain unreadable original bytes before an explicit edit can replace their concern. */
function preserveCorruptValues(): boolean {
  if (!corruptValues.size) return true;
  const previous = readRaw(RECOVERY_KEY);
  let saved: Record<string, string> = {};
  if (previous) {
    try { const envelope = JSON.parse(previous) as StoredValue; if (envelope.version !== 1 || typeof envelope.value !== "string") throw new Error("Unknown recovery version"); const parsed: unknown = JSON.parse(envelope.value); if (!objectValue(parsed) || Object.values(parsed).some(value => typeof value !== "string")) throw new Error("Invalid recovery payload"); saved = parsed as Record<string, string>; }
    catch { saved[`${RECOVERY_KEY}:previous`] = previous; }
  }
  const recovery = { ...saved, ...Object.fromEntries(corruptValues) };
  const okay = writeRaw(RECOVERY_KEY, JSON.stringify({ version: 1, value: JSON.stringify(recovery) }));
  return okay;
}

/** Decode a versioned concern, migrating a valid old scalar/JSON payload exactly once. */
function readProductionValue(key: string): string | null {
  const canonical = versionedKey(key);
  let source = canonical; let raw = readRaw(canonical);
  if (raw === null && canonical !== key) { source = key; raw = readRaw(key); }
  if (raw === null) return null;
  const version = keyVersion(canonical);
  if (!(canonical.startsWith("docreview:conversations:") ? [1, 2].includes(version) : version === 1)) {
    corruptValues.set(source, raw); storageWarning("version", source); return null;
  }
  let value = raw; let migrated = true;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (objectValue(parsed) && "version" in parsed && "value" in parsed) {
      if (parsed.version !== keyVersion(canonical) || typeof parsed.value !== "string") {
        corruptValues.set(source, raw); storageWarning("version", source); return null;
      }
      value = parsed.value; migrated = false;
    }
  } catch { /* Scalar legacy preferences are validated below, never evaluated. */ }
  if (!validStoredValue(canonical, value)) {
    corruptValues.set(source, raw); storageWarning("corrupt", source); return null;
  }
  if (migrated) {
    if (writeRaw(canonical, JSON.stringify({ version: keyVersion(canonical), value })) && source !== canonical) writeRaw(source, null);
  }
  return value;
}

/** Inventory physical records plus unsaved session updates without touching other apps. */
function storedEntries(): Array<[string, string]> {
  const entries = new Map<string, string>();
  try {
    const store = rawBrowserStorage();
    for (let i = 0; i < store.length; i++) {
      const key = store.key(i); if (key && ownedStorageKey(key)) { const value = store.getItem(key); if (value !== null) entries.set(key, value); }
    }
  } catch {
    if (productionBrowserStorageEnabled()) {
      storageWarning("unavailable", "docreview:");
      for (const [key, value] of knownValues) if (value !== null && !entries.has(key)) entries.set(key, value);
    }
  }
  if (productionBrowserStorageEnabled()) for (const [key, value] of sessionValues) { if (value === null) entries.delete(key); else entries.set(key, value); }
  return [...entries].sort(([a], [b]) => a.localeCompare(b));
}

const productionStorage: Storage = {
  get length() { return storedEntries().length; },
  key: (index) => storedEntries()[index]?.[0] ?? null,
  getItem: (key) => readProductionValue(String(key)),
  setItem: (key, value) => {
    const canonical = versionedKey(String(key)); const text = String(value);
    if (!ownedStorageKey(canonical) || !validStoredValue(canonical, text)) { storageWarning("corrupt", canonical); return; }
    const raw = JSON.stringify({ version: keyVersion(canonical), value: text });
    if (!preserveCorruptValues()) { sessionValues.set(canonical, raw); return; }
    if (writeRaw(canonical, raw)) {
      for (const key of [...corruptValues.keys()]) if (versionedKey(key) === canonical) {
        corruptValues.delete(key); if (key !== canonical) writeRaw(key, null);
      }
    }
  },
  removeItem: (key) => { if (ownedStorageKey(key)) { writeRaw(versionedKey(key), null); if (versionedKey(key) !== key) writeRaw(key, null); } },
  clear: () => { for (const [key] of storedEntries()) writeRaw(key, null); },
};

/** Read a previously deployed profile after a same-origin return to DEV without migrating DEV writes. */
const developmentStorage: Storage = {
  get length() { return rawBrowserStorage().length; },
  key: index => rawBrowserStorage().key(index),
  clear: () => rawBrowserStorage().clear(),
  removeItem: key => rawBrowserStorage().removeItem(key),
  setItem: (key, value) => rawBrowserStorage().setItem(key, value),
  getItem: key => {
    const raw = rawBrowserStorage().getItem(key) ?? (ownedStorageKey(key) ? rawBrowserStorage().getItem(versionedKey(key)) : null);
    if (raw === null) return null;
    try {
      const parsed: unknown = JSON.parse(raw);
      if (objectValue(parsed) && parsed.version === keyVersion(versionedKey(key)) && typeof parsed.value === "string" && validStoredValue(versionedKey(key), parsed.value)) return parsed.value;
    } catch { /* Preserve the DEV reader's existing raw scalar behavior. */ }
    return raw;
  },
};

/** All consumers share this boundary; only real PROD migrates or uses quota fallback. */
export function browserStorage(): Storage {
  if (previewState().mode !== "normal") return rawBrowserStorage();
  return productionBrowserStorageEnabled() ? productionStorage : storageEnvironment === "dev" ? developmentStorage : rawBrowserStorage();
}

/** Persist only the selected conversation identity; URL navigation still takes precedence. */
export function loadActiveConversation(): string | null { return productionBrowserStorageEnabled() ? browserStorage().getItem(ACTIVE_CONVERSATION_KEY) : null; }
export function saveActiveConversation(id: string): void { if (productionBrowserStorageEnabled() && id) browserStorage().setItem(ACTIVE_CONVERSATION_KEY, id); }

/** Report per-key UTF-16 storage estimates; browser quota policies vary by origin. */
export function browserStorageBreakdown(): Array<{ key: string; bytes: number }> {
  return storedEntries().map(([key, value]) => ({ key, bytes: 2 * (key.length + value.length) }));
}

/** Export original serialized payloads and schema versions, including unsaved session data. */
export function exportBrowserSettings(): string {
  if (!productionBrowserStorageEnabled()) throw new Error("Browser settings export is available on the deployed screen.");
  preserveCorruptValues();
  const entries = storedEntries().filter(([key]) => !corruptValues.has(key) || sessionValues.has(key)).map(([key, value]) => ({ key, version: keyVersion(key), value }));
  return JSON.stringify({ format: "docreview-browser-storage", version: 1, entries } satisfies BrowserStorageExport, null, 2);
}

/** Validate the entire file before confirmation or any browser storage write. */
export function validateBrowserSettings(text: string): BrowserStorageExport {
  const value: unknown = JSON.parse(text);
  if (!objectValue(value) || value.format !== "docreview-browser-storage" || value.version !== 1 || !Array.isArray(value.entries)) throw new Error("Unsupported browser settings file.");
  const seen = new Set<string>();
  for (const entry of value.entries) {
    if (!objectValue(entry) || typeof entry.key !== "string" || !ownedStorageKey(entry.key) || seen.has(entry.key) || entry.version !== keyVersion(entry.key) || typeof entry.value !== "string") throw new Error("Invalid browser settings entry.");
    seen.add(entry.key);
    if (!(entry.key.startsWith("docreview:conversations:") ? [1, 2].includes(entry.version as number) : [0, 1].includes(entry.version as number))) throw new Error("Unsupported setting version.");
    // Recovery bytes may be exported without being executable settings; known values must validate.
    if (entry.key !== RECOVERY_KEY) {
      let raw = entry.value;
      try {
        const envelope: unknown = JSON.parse(raw);
        if (objectValue(envelope) && "version" in envelope && "value" in envelope) {
          if (envelope.version !== entry.version || typeof envelope.value !== "string") throw new Error("Unsupported setting version.");
          raw = envelope.value;
        }
      } catch (error) { if (!(error instanceof SyntaxError)) throw error; }
      if (!validStoredValue(versionedKey(entry.key), raw)) throw new Error("Invalid browser settings payload.");
    }
  }
  return value as unknown as BrowserStorageExport;
}

/** Replace only application-owned keys after explicit confirmation, retaining a session fallback. */
export function importBrowserSettings(text: string, confirmed: boolean): boolean {
  if (!productionBrowserStorageEnabled() || !confirmed) return false;
  const parsed = validateBrowserSettings(text);
  const incoming = new Map(parsed.entries.map(entry => [entry.key, entry.value]));
  let persisted = true;
  for (const [key] of storedEntries()) if (!incoming.has(key)) persisted = writeRaw(key, null) && persisted;
  for (const [key, value] of incoming) persisted = writeRaw(key, value) && persisted;
  corruptValues.clear();
  window.dispatchEvent(new Event(STORAGE_CHANGED_EVENT));
  window.dispatchEvent(new Event("docreview:retrieval-presets-changed"));
  return persisted;
}

/** Reload application state after an import without dropping a quota-failure session overlay. */
export function subscribeStorageRestored(listener: () => void): () => void {
  window.addEventListener(STORAGE_CHANGED_EVENT, listener);
  return () => window.removeEventListener(STORAGE_CHANGED_EVENT, listener);
}

/** Keep raw destructive browser-reset access centralized; callers retain existing confirmation. */
export function browserResetStores(): Storage[] { return [rawBrowserStorage(), window.sessionStorage]; }

// Kept outside portable preference keys so imports cannot replay a fresh-start receipt.
export const FRESH_START_RECEIPT_KEY = "docreview.fresh-start";

/** Consume an explicit server reset once, clearing only this application's browser keys. */
export function applyFreshStartReset(resetId: string | null | undefined): boolean {
  if (!resetId || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(resetId) || typeof window === "undefined") return false;
  const [local, session] = browserResetStores();
  const resetLocal = local.getItem(FRESH_START_RECEIPT_KEY) !== resetId;
  const resetSession = session.getItem(FRESH_START_RECEIPT_KEY) !== resetId;
  if (!resetLocal && !resetSession) return false;
  for (const store of resetLocal ? [local, session] : [session]) {
    const keys = Array.from({ length: store.length }, (_, index) => store.key(index)).filter((key): key is string => key !== null && ownedStorageKey(key));
    for (const key of keys) store.removeItem(key);
  }
  sessionValues.clear(); knownValues.clear(); corruptValues.clear(); warnings.clear();
  session.setItem(FRESH_START_RECEIPT_KEY, resetId);
  // Acknowledge only after both stores were cleared successfully; other tabs observe this write.
  if (resetLocal) local.setItem(FRESH_START_RECEIPT_KEY, resetId);
  return true;
}

/** Pre-paint preference read, generated here so components never access localStorage directly. */
export function browserThemeBootstrap(legacyKey: string): string {
  const allowVersioned = process.env.NEXT_PUBLIC_ADMIN_MODE !== "live";
  return `(function(){var t="system";try{var p=window.name==="docreview-production-preview";var v=p?new URLSearchParams(location.search).get("theme"):localStorage.getItem(${JSON.stringify(legacyKey)});if(!p&&!v&&${allowVersioned}){var s=JSON.parse(localStorage.getItem("docreview:theme:v1")||"null");if(s&&s.version===1)v=s.value;}if(v==="light"||v==="dark")t=v;}catch(e){}var d=t==="system"?(window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"):t;document.documentElement.dataset.theme=t;document.documentElement.dataset.colorMode=d;document.documentElement.style.colorScheme=d;})();`;
}

/** Raw-value boundary shared with the browser-local preset implementation. */
export function readStoredValue(key: string): string | null { return browserStorage().getItem(key); }
/** Persist a serialized setting through the selected DEV, PROD or preview transport. */
export function writeStoredValue(key: string, value: string): void { browserStorage().setItem(key, value); }

/** Decode cross-tab preference events through the same version and payload checks. */
export function storageEventValue(event: StorageEvent, key: string): string | null | undefined {
  if (event.key !== key && event.key !== versionedKey(key)) return undefined;
  if (event.newValue === null) return null;
  let raw = event.newValue;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (objectValue(parsed) && "version" in parsed && "value" in parsed) {
      if (parsed.version !== keyVersion(versionedKey(key)) || typeof parsed.value !== "string") return undefined;
      raw = parsed.value;
    }
  } catch { /* Existing scalar preference events are validated below. */ }
  return validStoredValue(versionedKey(key), raw) ? raw : undefined;

}
