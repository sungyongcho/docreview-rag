import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Readiness, ReviewSessionProfile } from "@/lib/types";
import { DEFAULT_PROFILE, DEFAULT_SESSION_PROFILE } from "@/lib/types";
import { ComposerBanner, ComposerToolbar, composerBanner, readinessChipLabel, type ComposerToolbarProps } from "./composer-toolbar";

const READINESS: Readiness = {
  status: "ready",
  mode: "runtime",
  admin_mode: "live",
  policy_revision: "test",
  models: {},
  review_enabled: true,
  active_review_model: "gpt-5.6-terra",
  review_engines: { openai: { enabled: true, model: "gpt-5.6-terra", key_slot: "dev" }, local: { enabled: false } },
  corpus: {
    availability: "ready",
    database_connected: true,
    schema_status: "compatible",
    schema_message: "ok",
    documents: 29,
    chunks: 21927,
    embedded_chunks: 21927,
    pending_embeddings: 0,
    bm25_ready: true,
    writable: true,
  },
};

function readiness(overrides: Partial<Readiness["corpus"]> = {}, top: Partial<Readiness> = {}): Readiness {
  return { ...READINESS, ...top, corpus: { ...READINESS.corpus, ...overrides } };
}

function renderToolbar(overrides: Partial<ComposerToolbarProps> = {}) {
  const props: ComposerToolbarProps = {
    profile: DEFAULT_SESSION_PROFILE,
    onChange: vi.fn(),
    canUseCustom: true,
    onLocked: vi.fn(),
    onOpenFilters: vi.fn(),
    readiness: READINESS,
    live: true,
    onOpenBuild: vi.fn(),
    ...overrides,
  };
  render(<ComposerToolbar {...props} />);
  return props;
}

afterEach(cleanup);

describe("readinessChipLabel", () => {
  it("covers read-only, checking, empty, pending, and ready corpora", () => {
    expect(readinessChipLabel(READINESS, false)).toBe("Read-only corpus");
    expect(readinessChipLabel(null, true)).toBe("Checking corpus…");
    expect(readinessChipLabel(readiness({ documents: 0 }), true)).toBe("Corpus empty");
    expect(readinessChipLabel(readiness({ pending_embeddings: 120 }), true)).toBe("Embeddings pending · lexical only");
    expect(readinessChipLabel(READINESS, true)).toBe("29 filings · hybrid ready");
    expect(readinessChipLabel(readiness({ bm25_ready: false }), true)).toBe("29 filings · vector only");
  });
});

describe("composerBanner", () => {
  const vectorProfile: ReviewSessionProfile = { ...DEFAULT_SESSION_PROFILE, retrieval_preset: "custom", custom_retrieval: { ...DEFAULT_PROFILE, strategy: "vector" } };
  const resetAt = "2026-09-03T00:00:00Z";

  it("returns null when nothing blocks the composer", () => {
    expect(composerBanner({ readiness: READINESS, live: true, profile: DEFAULT_SESSION_PROFILE, resetAt: null })).toBeNull();
    expect(composerBanner({ readiness: null, live: false, profile: DEFAULT_SESSION_PROFILE, resetAt: null })).toBeNull();
  });

  it("ranks empty corpus above vector-only, answer model, and budget", () => {
    const everything = readiness({ documents: 0, pending_embeddings: 5 }, { review_enabled: false });
    expect(composerBanner({ readiness: everything, live: true, profile: vectorProfile, resetAt })).toMatchObject({ kind: "empty", action: "build" });
    expect(composerBanner({ readiness: everything, live: false, profile: vectorProfile, resetAt })).toMatchObject({ kind: "vector", action: "build" });
    const pendingOff = readiness({ pending_embeddings: 5 }, { review_enabled: false });
    expect(composerBanner({ readiness: pendingOff, live: true, profile: DEFAULT_SESSION_PROFILE, resetAt })).toMatchObject({
      kind: "answer-model",
      text: "Answer model is off — evidence only. Questions return retrieved filing evidence without a generated answer.",
      action: "answer-model",
    });
    const budget = composerBanner({ readiness: READINESS, live: true, profile: DEFAULT_SESSION_PROFILE, resetAt });
    expect(budget?.kind).toBe("budget");
    expect(budget?.action).toBeUndefined();
    expect(budget?.text).toBe(`Daily answer budget is used up. Evidence still loads; answers resume at ${new Date(resetAt).toLocaleString()}.`);
  });

  it("renders the banner text and its action button", () => {
    const onOpenBuild = vi.fn();
    const onOpenAnswerModel = vi.fn();
    expect(composerBanner({ readiness: readiness({ documents: 0 }), live: true, profile: DEFAULT_SESSION_PROFILE, resetAt: null })?.text).toBe("The corpus is empty. Build it first.");
    const { rerender } = render(<ComposerBanner banner={{ kind: "empty", text: "The corpus is empty. Build it first.", action: "build" }} onOpenBuild={onOpenBuild} onOpenAnswerModel={onOpenAnswerModel} />);
    expect(screen.getByRole("status")).toHaveClass("composer-banner", "empty");
    fireEvent.click(screen.getByRole("button", { name: "Open Build" }));
    expect(onOpenBuild).toHaveBeenCalledTimes(1);
    rerender(<ComposerBanner banner={{ kind: "answer-model", text: "off", action: "answer-model" }} onOpenBuild={onOpenBuild} onOpenAnswerModel={onOpenAnswerModel} />);
    fireEvent.click(screen.getByRole("button", { name: "Set up the answer model" }));
    expect(onOpenAnswerModel).toHaveBeenCalledTimes(1);
    rerender(<ComposerBanner banner={null} onOpenBuild={onOpenBuild} onOpenAnswerModel={onOpenAnswerModel} />);
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("ComposerToolbar", () => {
  it("writes corpus_scope from the scope segmented control", () => {
    const props = renderToolbar();
    const group = screen.getByRole("group", { name: "Corpus scope" });
    expect(within(group).getByRole("button", { name: "Auto" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(group).getByRole("button", { name: "SEC" }));
    expect(props.onChange).toHaveBeenCalledWith({ corpus_scope: "sec" });
  });

  it("applies presets and clears custom retrieval for built-in presets", () => {
    const props = renderToolbar({ profile: { ...DEFAULT_SESSION_PROFILE, retrieval_preset: "custom", custom_retrieval: { ...DEFAULT_PROFILE, k: 9 } } });
    fireEvent.change(screen.getByLabelText("Retrieval preset"), { target: { value: "korean" } });
    expect(props.onChange).toHaveBeenCalledWith({ retrieval_preset: "korean", custom_retrieval: null });
  });

  it("seeds custom retrieval from the default profile when Custom is allowed", () => {
    const props = renderToolbar();
    fireEvent.change(screen.getByLabelText("Retrieval preset"), { target: { value: "custom" } });
    expect(props.onLocked).not.toHaveBeenCalled();
    expect(props.onChange).toHaveBeenCalledWith({ retrieval_preset: "custom", custom_retrieval: DEFAULT_PROFILE });
  });

  it("hides Custom on public builds unless the session already uses it, and locks it when chosen", () => {
    renderToolbar({ canUseCustom: false });
    expect(screen.queryByRole("option", { name: "Custom" })).toBeNull();
    cleanup();
    const props = renderToolbar({ canUseCustom: false, profile: { ...DEFAULT_SESSION_PROFILE, retrieval_preset: "custom", custom_retrieval: DEFAULT_PROFILE } });
    expect(screen.getByRole("option", { name: "Custom" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Retrieval preset"), { target: { value: "balanced" } });
    fireEvent.change(screen.getByLabelText("Retrieval preset"), { target: { value: "custom" } });
    expect(props.onLocked).toHaveBeenCalledTimes(1);
    expect(props.onChange).toHaveBeenCalledTimes(1);
    expect(props.onChange).toHaveBeenCalledWith({ retrieval_preset: "balanced", custom_retrieval: null });
  });

  it("counts active filters on the Filters chip and opens the session filters", () => {
    const props = renderToolbar({ profile: { ...DEFAULT_SESSION_PROFILE, issuers: ["NVDA"], fiscal_years: [2024], languages: ["en"] } });
    fireEvent.click(screen.getByRole("button", { name: "Filters · 3" }));
    expect(props.onOpenFilters).toHaveBeenCalledTimes(1);
    cleanup();
    renderToolbar();
    expect(screen.getByRole("button", { name: "Filters" })).toBeInTheDocument();
  });

  it("shows the snapshot chip only when set and clears it with the × button", () => {
    const props = renderToolbar({ profile: { ...DEFAULT_SESSION_PROFILE, snapshot_id: 7, applied_from_evaluation: "eval-1" } });
    expect(screen.getByText("Snapshot #7")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear snapshot" }));
    expect(props.onChange).toHaveBeenCalledWith({ snapshot_id: null, applied_from_evaluation: null });
    cleanup();
    renderToolbar();
    expect(screen.queryByText(/Snapshot #/)).toBeNull();
  });

  it("routes the readiness chip to Build", () => {
    const props = renderToolbar({ live: false });
    fireEvent.click(screen.getByRole("button", { name: "Read-only corpus" }));
    expect(props.onOpenBuild).toHaveBeenCalledTimes(1);
  });
});
