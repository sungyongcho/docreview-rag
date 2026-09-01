import { beforeEach, describe, expect, it, vi } from "vitest";

import { loadConversations, newConversation, saveConversations } from "./storage";

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
});
