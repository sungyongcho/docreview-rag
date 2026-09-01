import type { Conversation } from "./types";
import { DEFAULT_SESSION_PROFILE } from "./types";

const STORAGE_KEY = "docreview:conversations:v2";
const LEGACY_STORAGE_KEY = "docreview:conversations:v1";
export const ONBOARDING_KEY = "docreview:onboarding:v1";
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
    profile: DEFAULT_SESSION_PROFILE,
  };
}

function migrateConversation(conversation: Conversation): Conversation {
  const profile = conversation.profile as unknown as Record<string, unknown> | null;
  if (profile && "engine" in profile) return conversation;
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
