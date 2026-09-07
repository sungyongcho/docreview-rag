import { beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_PROFILE, DEFAULT_SESSION_PROFILE } from "./types";
import { conversationSettingsError, loadSavedPresets, savePreset } from "./saved-presets";

beforeEach(() => localStorage.clear());
describe("saved retrieval presets", () => {
  it("updates only the named entry and leaves conversation defaults and prior copies unchanged", () => {
    const first = { id: "first", name: "Research", retrieval: { ...DEFAULT_PROFILE, k: 8 } };
    savePreset(first);
    savePreset({ id: "second", name: "Brief", retrieval: DEFAULT_PROFILE });
    const copy = loadSavedPresets()[0].retrieval;
    savePreset({ ...first, retrieval: { ...first.retrieval, k: 10 } });
    expect(loadSavedPresets().map(p => [p.name, p.retrieval.k])).toEqual([["Research", 10], ["Brief", 5]]);
    expect(copy.k).toBe(8);
    expect(DEFAULT_SESSION_PROFILE.retrieval_preset).toBe("balanced");
  });
  it("rejects duplicate names, incompatible strategies and malformed storage without overwriting data", () => {
    savePreset({ id: "one", name: "Research", retrieval: DEFAULT_PROFILE });
    expect(() => savePreset({ id: "two", name: " research ", retrieval: DEFAULT_PROFILE })).toThrow(/already exists/);
    expect(() => savePreset({ id: "two", name: "Other", retrieval: { ...DEFAULT_PROFILE, strategy: "vector", lexical_ranker: null, route_by_language: true } })).toThrow(/hybrid/);
    expect(loadSavedPresets()).toHaveLength(1);
    localStorage.setItem("docreview:retrieval-presets:v1", "broken");
    expect(() => savePreset({ id: "three", name: "Third", retrieval: DEFAULT_PROFILE })).toThrow();
    expect(localStorage.getItem("docreview:retrieval-presets:v1")).toBe("broken");
  });
  it("validates hidden settings and permits explicitly supported zero-token limits", () => {
    const profile = structuredClone(DEFAULT_SESSION_PROFILE);
    profile.prompt_policy.workflow_budget.max_output_tokens = 0;
    expect(conversationSettingsError(profile)).toBeNull();
    profile.prompt_policy.max_context_chars = 999;
    expect(conversationSettingsError(profile)).toMatch(/ranges/);
  });
});
