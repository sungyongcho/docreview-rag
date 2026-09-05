import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Readiness, ReviewSessionProfile } from "@/lib/types";
import { DEFAULT_PROFILE, DEFAULT_SESSION_PROFILE } from "@/lib/types";
import { ComposerBanner, ComposerToolbar, composerBanner, readinessChipLabel, readinessStatusLabel, type ComposerToolbarProps } from "./composer-toolbar";

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

describe("corpus readiness summary", () => {
  it("labels the global corpus and omits unpublished totals in public mode", () => {
    expect(readinessChipLabel(READINESS, false)).toBe("Published corpus");
    expect(readinessChipLabel(null, true)).toBe("Corpus total");
    expect(readinessChipLabel(readiness({ documents: 0 }), true)).toBe("Corpus total · 0 filings");
    expect(readinessChipLabel(READINESS, true)).toBe("Corpus total · 29 filings");
    expect(readinessChipLabel(readiness({ database_connected: false }), true)).toBe("Corpus total");
  });

  it("reports only confirmed index readiness and never treats unknown values as success", () => {
    expect(readinessStatusLabel(null)).toBe("Checking corpus…");
    expect(readinessStatusLabel(readiness({ documents: 0 }))).toBe("Corpus empty");
    expect(readinessStatusLabel(readiness({ pending_embeddings: 120 }))).toBe("Embeddings pending");
    expect(readinessStatusLabel(READINESS)).toBe("Hybrid search ready");
    expect(readinessStatusLabel(readiness({ bm25_ready: false }))).toBe("Vector search ready · BM25 unavailable");
    for (const unknown of [{ bm25_ready: null }, { database_connected: null }, { pending_embeddings: null }, { documents: null }, { schema_status: null }] as const) {
      expect(readinessStatusLabel(readiness(unknown))).toBe("Readiness not confirmed");
    }
    expect(readinessStatusLabel(readiness({ database_connected: false }))).toBe("Corpus unavailable");
    expect(readinessStatusLabel(readiness({ availability: "not_applicable", database_connected: null, bm25_ready: null }))).toBe("Readiness not reported");
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
    expect(screen.getByText("Snapshot #7").closest('[data-help="review.snapshot"]')).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Clear snapshot" }));
    expect(props.onChange).toHaveBeenCalledWith({ snapshot_id: null, applied_from_evaluation: null });
    cleanup();
    renderToolbar();
    expect(screen.queryByText(/Snapshot #/)).toBeNull();
  });

  it("routes the readiness chip to Build", () => {
    const props = renderToolbar({ live: false });
    expect(screen.getByText("Published corpus")).toBeVisible();
    expect(screen.queryByText(/Corpus total ·/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "View corpus readiness" }));
    expect(props.onOpenBuild).toHaveBeenCalledTimes(1);
  });

  it("explains selected scope and preset beside the controls before opening details", () => {
    renderToolbar({ profile: { ...DEFAULT_SESSION_PROFILE, retrieval_preset: "accuracy" } });
    expect(screen.getByText("Corpus scope")).toBeVisible();
    expect(screen.getByText("Retrieval preset")).toBeVisible();
    expect(screen.getByText("Automatic source routing")).toBeVisible();
    expect(screen.getByText("hybrid · k 5 · Candidates 50")).toBeVisible();
    fireEvent.mouseEnter(screen.getByRole("button", { name: "About retrieval presets" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Ranks a wider candidate pool by relevance.");
    expect(screen.getByRole("tooltip")).toHaveTextContent("candidate_k: 50");
    expect(screen.getByRole("tooltip")).toHaveTextContent("reranker: cross_encoder");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

it("opens corpus help from hover, focus, and touch click and dismisses with Escape", () => {
  renderToolbar();
  const help = screen.getByRole("button", { name: "About corpus scope" });
  fireEvent.mouseEnter(help);
  expect(screen.getByRole("tooltip")).toHaveTextContent("Auto chooses SEC or DART from the question and filters.");
  fireEvent.mouseLeave(help);
  expect(screen.queryByRole("tooltip")).toBeNull();
  fireEvent.focus(help);
  expect(screen.getByRole("tooltip")).toBeVisible();
  fireEvent.keyDown(help, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).toBeNull();
  fireEvent.click(help);
  expect(screen.getByRole("tooltip")).toBeVisible();
  fireEvent.click(help);
  expect(screen.queryByRole("tooltip")).toBeNull();
});

it("opens the current Custom editor immediately and preserves the custom values", () => {
  const onOpenCustom = vi.fn();
  const custom = { ...DEFAULT_PROFILE, k: 9, candidate_k: 37 };
  const props = renderToolbar({ onOpenCustom, profile: { ...DEFAULT_SESSION_PROFILE, retrieval_preset: "custom", custom_retrieval: custom } });
  fireEvent.change(screen.getByLabelText("Retrieval preset"), { target: { value: "custom" } });
  expect(props.onChange).toHaveBeenCalledWith({ retrieval_preset: "custom", custom_retrieval: custom });
  expect(onOpenCustom).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Edit custom retrieval" }));
  expect(onOpenCustom).toHaveBeenCalledTimes(2);
});

it("keeps selected source filters distinct from the global corpus count and unconfirmed status", () => {
  renderToolbar({ profile: { ...DEFAULT_SESSION_PROFILE, corpus_scope: "dart" }, readiness: readiness({ bm25_ready: null }) });
  expect(screen.getByText("Corpus total · 29 filings")).toBeVisible();
  expect(screen.getByText("Readiness not confirmed")).not.toHaveClass("confirmed");
  expect(screen.queryByText("Hybrid search ready")).toBeNull();
  expect(screen.getByRole("button", { name: "View corpus readiness" })).toBeVisible();
});
