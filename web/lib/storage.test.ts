import { beforeEach, describe, expect, it, vi } from "vitest";

import { loadConversations, loadExperimentDefaults, newConversation, resetExperimentDefaults, saveConversations, saveExperimentDefaults } from "./storage";
import { DEFAULT_EXPERIMENT_DEFAULTS } from "./types";

describe("conversation storage", () => {
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
      snapshot_id: 11,
      mode: "matrix" as const,
      baseline_snapshot_id: 9,
      retrieval_preset: "accuracy" as const,
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
