import { beforeEach, describe, expect, it, vi } from "vitest";

import { loadConversations, loadExperimentDefaults, loadOperationsFilter, loadOperationsTargetFilter, newConversation, resetExperimentDefaults, saveConversations, saveExperimentDefaults, saveOperationsFilter, saveOperationsTargetFilter } from "./storage";
import { DEFAULT_EXPERIMENT_DEFAULTS, DEFAULT_SESSION_PROFILE } from "./types";

describe("conversation storage", () => {
  it("stores the Operations target independently and rejects an unknown saved target", () => {
    saveOperationsFilter("verify");
    saveOperationsTargetFilter("database");
    expect(loadOperationsFilter()).toBe("verify");
    expect(loadOperationsTargetFilter()).toBe("database");
    window.localStorage.setItem("docreview:operations-target-filter:v1", "future-target");
    expect(loadOperationsTargetFilter()).toBe("all");
    expect(loadOperationsFilter()).toBe("verify");
    saveOperationsTargetFilter("web");
    saveOperationsTargetFilter("all");
    expect(window.localStorage.getItem("docreview:operations-target-filter:v1")).toBeNull();
  });

  beforeEach(() => {
    window.localStorage.clear();
    vi.stubGlobal("crypto", { randomUUID: () => "conversation-id" });
  });

  it("creates and restores a browser-persistent conversation", () => {
    const conversation = newConversation();
    saveConversations([conversation]);

    expect(loadConversations()).toEqual([conversation]);
    expect(conversation.id).toBe("conversation-id");
  });

  it("preserves unsent drafts and restores older conversations without them", () => {
    const older = newConversation();
    const drafted = { ...older, id: "drafted", draft: "  삼성전자 revenue\nFollow-up question  " };
    saveConversations([older, drafted]);

    expect(loadConversations()).toEqual([older, drafted]);
    expect(loadConversations()[0].draft).toBeUndefined();
    expect(loadConversations()[1].draft).toBe(drafted.draft);
  });

  it("rejects non-text drafts before restoring a conversation", () => {
    window.localStorage.setItem("docreview:conversations:v2", JSON.stringify([{ ...newConversation(), draft: { text: "invalid" } }]));

    expect(loadConversations()).toEqual([]);
  });

  it("bounds conversations and messages", () => {
    const conversations = Array.from({ length: 35 }, (_, index) => ({
      ...newConversation(),
      id: `conversation-${index}`,
      updatedAt: new Date(2026, 0, index + 1).toISOString(),
      messages: Array.from({ length: 110 }, (_, message) => ({
        id: `${index}-${message}`,
        role: "user" as const,
        text: String(message),
      })),
    }));

    const stored = saveConversations(conversations);

    expect(stored).toHaveLength(30);
    expect(stored.every((conversation) => conversation.messages.length === 100)).toBe(true);
  });

  it("persists versioned experiment defaults and resets them independently", () => {
    const configured = {
      ...DEFAULT_EXPERIMENT_DEFAULTS,
      suite_id: "dart-ko" as const,
      golden_revision_id: 7,
      mode: "matrix" as const,
    };

    saveExperimentDefaults(configured);
    expect(loadExperimentDefaults()).toEqual(configured);
    resetExperimentDefaults();
    expect(loadExperimentDefaults()).toEqual(DEFAULT_EXPERIMENT_DEFAULTS);
  });

  it("repairs invalid experiment default enum values and identifiers", () => {
    window.localStorage.setItem("docreview:experiment-defaults:v1", JSON.stringify({
      suite_id: "unknown",
      golden_revision_id: -1,
      snapshot_id: "3",
      mode: "expensive",
      baseline_snapshot_id: 0,
      retrieval_preset: "unsafe",
    }));

    expect(loadExperimentDefaults()).toEqual(DEFAULT_EXPERIMENT_DEFAULTS);
  });
});

it("restores old conversation profiles without a model and remembers new selections", () => {
  window.localStorage.clear();
  const { local_model: _removed, ...oldProfile } = DEFAULT_SESSION_PROFILE;
  const conversation = { ...newConversation(), profile: { ...oldProfile, engine: "local" as const } };
  window.localStorage.setItem("docreview:conversations:v2", JSON.stringify([conversation]));
  expect(loadConversations()[0].profile?.local_model).toBeNull();
  saveConversations([{ ...conversation, profile: { ...conversation.profile, local_model: "chosen" } }]);
  expect(loadConversations()[0].profile?.local_model).toBe("chosen");
});

describe("operations filter storage", () => {
  beforeEach(() => window.localStorage.clear());

  it("remembers the Operations category filter and ignores unknown values", () => {
    expect(loadOperationsFilter()).toBe("all");
    saveOperationsFilter("service");
    expect(window.localStorage.getItem("docreview:operations-filter:v1")).toBe("service");
    expect(loadOperationsFilter()).toBe("service");

    window.localStorage.setItem("docreview:operations-filter:v1", "bogus");
    expect(loadOperationsFilter()).toBe("all");

    saveOperationsFilter("all");
    expect(window.localStorage.getItem("docreview:operations-filter:v1")).toBeNull();
  });
});


it("drops retired snapshot and chat-preset fields from saved evaluation defaults", () => {
  window.localStorage.setItem("docreview:experiment-defaults:v1", JSON.stringify({ suite_id: "dart-ko", golden_revision_id: null, mode: "quick", snapshot_id: 12, baseline_snapshot_id: 8, retrieval_preset: "accuracy" }));
  expect(loadExperimentDefaults()).toEqual({ suite_id: "dart-ko", golden_revision_id: null, mode: "quick" });
  expect(JSON.parse(window.localStorage.getItem("docreview:experiment-defaults:v1")!)).not.toHaveProperty("snapshot_id");
});
