import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Capabilities, Readiness, LocalModelInfo } from "@/lib/types";
import { DEFAULT_SESSION_PROFILE } from "@/lib/types";
import { loadDefaultProfile, saveDefaultProfile, saveConversations, loadConversations } from "@/lib/storage";
import { SettingsModal } from "./settings-modal";

const DEV: Capabilities = {
  environment: "dev",
  can_configure_local_llm: true,
  can_edit_prompt_policy: true,
  can_edit_run_limits: true,
  can_edit_golden: true,
  can_build_snapshot: true,
  can_run_evaluation: true,
  can_change_custom_retrieval: true,
  can_query_snapshot: true,
  can_use_operations: true,
  can_compare_published_snapshots: true,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.resetModules();
  window.localStorage.clear();
});

function renderSettings(capabilities: Capabilities, onClose = vi.fn()) {
  return render(<SettingsModal open profile={DEFAULT_SESSION_PROFILE} capabilities={capabilities} onChange={vi.fn()} onClose={onClose} onOpenTour={vi.fn()} onClear={vi.fn()} />);
}

  it("shows developer prompt policy while preserving the immutable guard", () => {
    renderSettings(DEV);
    expect(screen.getByRole("button", { name: "Prompt" })).toHaveAttribute("title", "DEV only");
    expect(screen.getByRole("button", { name: "Data & help" }).querySelector(".development-badge")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Prompt" }));

    expect(screen.getByLabelText("Immutable evidence guard")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Additional operator instructions")).toHaveAttribute("maxlength", "8000");
  });

  it("uses a distinct production menu and closes with Escape", () => {
    const onClose = vi.fn();
    renderSettings({ ...DEV, can_edit_prompt_policy: false }, onClose);

    expect(screen.queryByRole("button", { name: "Prompt" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Data & help" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Data & help" }).querySelector(".development-badge")).toBeNull();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

it("saves only prompt defaults and leaves existing conversation settings untouched", () => {
  saveDefaultProfile({ ...DEFAULT_SESSION_PROFILE, corpus_scope: "dart", local_model: "saved-model" });
  const stored = { id: "other", title: "Other", createdAt: "2026-09-04", updatedAt: "2026-09-04", messages: [], profile: DEFAULT_SESSION_PROFILE };
  saveConversations([stored]);
  const onChange = vi.fn();
  const profile = { ...DEFAULT_SESSION_PROFILE, prompt_policy: { ...DEFAULT_SESSION_PROFILE.prompt_policy, additional_instructions: "Be concise." } };
  render(<SettingsModal open profile={profile} capabilities={DEV} onChange={onChange} onClose={vi.fn()} onOpenTour={vi.fn()} onClear={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Save prompt for new conversations" }));
  expect(loadDefaultProfile()).toMatchObject({ corpus_scope: "dart", local_model: "saved-model", prompt_policy: { additional_instructions: "Be concise." } });
  expect(loadConversations()[0]).toEqual(stored);
  expect(onChange).not.toHaveBeenCalled();
  expect(screen.queryByLabelText("Answer engine")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Data & help" }));
  expect(screen.getByRole("button", { name: /Clear conversations/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Show tutorial/ })).toBeInTheDocument();
});

it("links to both guides in the same tab without changing the current conversation", () => {
  const onChange = vi.fn();
  const onClear = vi.fn();
  render(<SettingsModal open profile={DEFAULT_SESSION_PROFILE} capabilities={DEV} onChange={onChange} onClose={vi.fn()} onOpenTour={vi.fn()} onClear={onClear} />);
  fireEvent.click(screen.getByRole("button", { name: "Data & help" }));
  expect(screen.getByRole("link", { name: "User guide" })).not.toBeVisible();
  fireEvent.click(screen.getByText("Guides & development", { exact: true }));
  const link = screen.getByRole("link", { name: "User guide" });
  expect(link).toHaveAttribute("href", "/docreview-rag-agent/docs/en/");
  expect(link).not.toHaveAttribute("target");
  expect(screen.getByRole("link", { name: "Development log" })).toHaveAttribute("href", "/docreview-rag-agent/docs/en/development/");
  fireEvent.click(screen.getByRole("button", { name: "About" }));
  expect(screen.getByRole("link", { name: "Development log" })).not.toBeVisible();
  fireEvent.click(screen.getByText("Guides & development", { exact: true }));
  expect(screen.getByRole("link", { name: "Development log" })).not.toHaveAttribute("target");
  expect(onChange).not.toHaveBeenCalled();
  expect(onClear).not.toHaveBeenCalled();
});
