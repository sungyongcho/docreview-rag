import { afterEach, expect, it } from "vitest";
import { applyProdPolicy, newProdProfile } from "./prod-profile";
import { configureBrowserStorage, loadDefaultProfile, saveDefaultProfile, newConversation } from "./storage";
import { DEFAULT_SESSION_PROFILE } from "./types";

afterEach(() => { configureBrowserStorage(undefined); localStorage.clear(); });
it("does not inherit saved DEV defaults and does not overwrite them", () => {
  configureBrowserStorage("dev");
  const dev = structuredClone(DEFAULT_SESSION_PROFILE);
  dev.engine = "local"; dev.local_model = "test-local"; dev.prompt_policy.workflow_budget.max_wall_clock_s = 300;
  saveDefaultProfile(dev);
  configureBrowserStorage("prod");
  expect(newConversation().profile).toEqual(newProdProfile());
  expect(() => saveDefaultProfile(dev)).toThrow("PROD defaults are fixed");
  configureBrowserStorage("dev"); expect(loadDefaultProfile()).toEqual(dev);
});
it("returns independent public profiles with editable retrieval and fixed initial limits", () => {
  const first = newProdProfile(); first.retrieval_preset = "korean"; first.prompt_policy.workflow_budget.max_wall_clock_s = 999;
  expect(newProdProfile().prompt_policy.workflow_budget.max_wall_clock_s).toBe(120);
  expect(newProdProfile().retrieval_preset).toBe("balanced");
});

it("applies server policy to old DEV profiles while preserving allowed scope and presets", () => {
  const saved = newProdProfile(); saved.engine = "local"; saved.local_model = "old-model";
  saved.prompt_policy.workflow_budget.max_wall_clock_s = 999; saved.retrieval_preset = "korean";
  saved.doc_ids = ["AMD-2024"]; saved.fiscal_years = [2024];
  const original = structuredClone(saved); const server = newProdProfile().prompt_policy;
  const applied = applyProdPolicy(saved, server);
  expect(applied.engine).toBe("openai"); expect(applied.prompt_policy).toEqual(server);
  expect(applied.doc_ids).toEqual(saved.doc_ids); expect(applied.retrieval_preset).toBe("korean");
  expect(saved).toEqual(original);
});
