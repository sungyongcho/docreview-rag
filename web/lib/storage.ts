import type { Conversation, ExperimentDefaults, ReviewSessionProfile } from "./types";
import { DEFAULT_EXPERIMENT_DEFAULTS, DEFAULT_SESSION_PROFILE } from "./types";

const STORAGE_KEY = "docreview:conversations:v2";
const LEGACY_STORAGE_KEY = "docreview:conversations:v1";
export const ONBOARDING_KEY = "docreview:onboarding:v1";
const DEFAULT_PROFILE_KEY = "docreview:profile-defaults:v1";
const DESKTOP_JOB_NOTIFICATIONS_KEY = "docreview:desktop-job-notifications:v1";
const EXPERIMENT_DEFAULTS_KEY = "docreview:experiment-defaults:v1";
/** Help mode open/closed; separate from the frozen onboarding key so the tour sentinel never changes. */
export const HELP_KEY = "docreview:help:v1";
const MAX_CONVERSATIONS = 30;
const MAX_MESSAGES = 100;

export function loadConversations(): Conversation[] {
  if (typeof window === "undefined") return [];
  try {
    const current = window.localStorage.getItem(STORAGE_KEY);
    const value: unknown = JSON.parse(current ?? window.localStorage.getItem(LEGACY_STORAGE_KEY) ?? "[]");
    if (!Array.isArray(value)) return [];
    return value.filter(isConversation).map(migrateConversation).slice(0, MAX_CONVERSATIONS);
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
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(bounded));
  }
  return bounded;
}

export function newConversation(): Conversation {
  const now = new Date().toISOString();
  return {
    id: crypto.randomUUID(),
    title: "New review",
    createdAt: now,
    updatedAt: now,
    messages: [],
    profile: loadDefaultProfile(),
  };
}

export function loadDefaultProfile(): ReviewSessionProfile {
  if (typeof window === "undefined") return DEFAULT_SESSION_PROFILE;
  try {
    const value = JSON.parse(window.localStorage.getItem(DEFAULT_PROFILE_KEY) ?? "null") as Partial<ReviewSessionProfile> | null;
    return value ? mergeProfile(value) : DEFAULT_SESSION_PROFILE;
  } catch {
    return DEFAULT_SESSION_PROFILE;
  }
}

export function saveDefaultProfile(profile: ReviewSessionProfile): void {
  if (typeof window !== "undefined") window.localStorage.setItem(DEFAULT_PROFILE_KEY, JSON.stringify(profile));
}

export function resetDefaultProfile(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(DEFAULT_PROFILE_KEY);
}

export function loadExperimentDefaults(): ExperimentDefaults {
  if (typeof window === "undefined") return DEFAULT_EXPERIMENT_DEFAULTS;
  try {
    const value = JSON.parse(window.localStorage.getItem(EXPERIMENT_DEFAULTS_KEY) ?? "null") as Partial<ExperimentDefaults> | null;
    if (!value) return DEFAULT_EXPERIMENT_DEFAULTS;
    const suiteId = ["sec-en", "sec-ko", "dart-en", "dart-ko"].includes(String(value.suite_id))
      ? value.suite_id as ExperimentDefaults["suite_id"]
      : DEFAULT_EXPERIMENT_DEFAULTS.suite_id;
    const mode = value.mode === "matrix" || value.mode === "quick"
      ? value.mode
      : DEFAULT_EXPERIMENT_DEFAULTS.mode;
    const retrievalPreset = ["balanced", "korean", "accuracy", "custom"].includes(String(value.retrieval_preset))
      ? value.retrieval_preset as ExperimentDefaults["retrieval_preset"]
      : DEFAULT_EXPERIMENT_DEFAULTS.retrieval_preset;
    return {
      ...DEFAULT_EXPERIMENT_DEFAULTS,
      ...value,
      suite_id: suiteId,
      mode,
      retrieval_preset: retrievalPreset,
      golden_revision_id: positiveId(value.golden_revision_id),
      snapshot_id: positiveId(value.snapshot_id),
      baseline_snapshot_id: positiveId(value.baseline_snapshot_id),
    };
  } catch {
    return DEFAULT_EXPERIMENT_DEFAULTS;
  }
}

export function saveExperimentDefaults(value: ExperimentDefaults): void {
  if (typeof window !== "undefined") window.localStorage.setItem(EXPERIMENT_DEFAULTS_KEY, JSON.stringify(value));
}

export function resetExperimentDefaults(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(EXPERIMENT_DEFAULTS_KEY);
}

export function desktopJobNotificationsEnabled(): boolean {
  return typeof window !== "undefined"
    && window.localStorage.getItem(DESKTOP_JOB_NOTIFICATIONS_KEY) === "enabled";
}

export function setDesktopJobNotifications(enabled: boolean): void {
  if (typeof window === "undefined") return;
  if (enabled) window.localStorage.setItem(DESKTOP_JOB_NOTIFICATIONS_KEY, "enabled");
  else window.localStorage.removeItem(DESKTOP_JOB_NOTIFICATIONS_KEY);
}

export function loadHelpOpen(): boolean {
  return typeof window !== "undefined" && window.localStorage.getItem(HELP_KEY) === "open";
}

export function saveHelpOpen(open: boolean): void {
  if (typeof window === "undefined") return;
  if (open) window.localStorage.setItem(HELP_KEY, "open");
  else window.localStorage.removeItem(HELP_KEY);
}

export function browserStorageUsage(): number {
  // Count only application-owned keys; browser and third-party data stay outside this view.
  if (typeof window === "undefined") return 0;
  let bytes = 0;
  for (let index = 0; index < window.localStorage.length; index += 1) {
    const key = window.localStorage.key(index);
    if (!key?.startsWith("docreview:")) continue;
    bytes += new TextEncoder().encode(key + (window.localStorage.getItem(key) ?? "")).byteLength;
  }
  return bytes;
}


function mergeProfile(profile: Partial<ReviewSessionProfile>): ReviewSessionProfile {
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
      profile: mergeProfile(profile as Partial<ReviewSessionProfile>),
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
