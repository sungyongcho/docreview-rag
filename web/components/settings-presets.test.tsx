import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DEFAULT_SESSION_PROFILE, type ReviewSessionDraft } from "@/lib/types";
import { savePreset } from "@/lib/saved-presets";
import { ConversationSettings, type ConversationSettingsTab } from "./conversation-settings";
import { RetrievalPresetSelect } from "./retrieval-preset-select";
import { RetrievalPresetManager } from "./retrieval-preset-manager";

beforeEach(() => { localStorage.clear(); vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ issuers: [], languages: [], years: [], forms: [] }), { status: 200 }))); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

/** Model the same lifted conversation state used by ServiceShell. */
function Editor() {
  const [profile, setProfile] = useState<ReviewSessionDraft>(structuredClone(DEFAULT_SESSION_PROFILE));
  const [tab, setTab] = useState<ConversationSettingsTab>("limits");
  return <ConversationSettings profile={profile} tab={tab} editable query="Keep this question" onChange={update => setProfile(old => ({ ...old, ...update }))} onTabChange={setTab} onClose={() => {}} />;
}
it("keeps edited values across settings sections and previews the same request", () => {
  render(<Editor />);
  fireEvent.change(screen.getByLabelText("Maximum wall clock seconds"), { target: { value: "180" } });
  fireEvent.click(screen.getByRole("button", { name: "Filters" }));
  expect(screen.getByText("Search and policy changes from defaults: 1")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Preview" }));
  expect(screen.getByText("Keep this question")).toBeVisible();
  fireEvent.click(screen.getByText("Request payload"));
  expect(screen.getByText(/"query": "Keep this question"/)).toHaveTextContent('"max_wall_clock_s": 180');
  fireEvent.click(screen.getByRole("button", { name: "Run limits" }));
  expect(screen.getByLabelText("Maximum wall clock seconds")).toHaveValue(180);
});
it("saves a named copy and updates mounted selectors without applying it to a conversation", () => {
  const onChange = vi.fn();
  render(<><RetrievalPresetManager /><RetrievalPresetSelect profile={DEFAULT_SESSION_PROFILE} editable onChange={onChange} /></>);
  const card = screen.getByRole("button", { name: "Balanced" }).closest("section")!;
  fireEvent.click(within(card).getByRole("button", { name: "Balanced" }));
  fireEvent.click(within(card).getByRole("button", { name: "Copy and edit" }));
  fireEvent.change(screen.getByLabelText("Preset name"), { target: { value: "My research" } });
  fireEvent.change(screen.getByLabelText("k"), { target: { value: "8" } });
  fireEvent.click(screen.getByRole("button", { name: "Save preset" }));
  expect(onChange).not.toHaveBeenCalled();
  const option = screen.getByRole("option", { name: "My research" }) as HTMLOptionElement;
  fireEvent.change(screen.getByRole("combobox", { name: "Retrieval preset" }), { target: { value: option.value } });
  expect(onChange).toHaveBeenCalledWith({ retrieval_preset: "custom", custom_retrieval: expect.objectContaining({ k: 8 }) });
  cleanup();
  render(<RetrievalPresetManager />);
  expect(screen.getByText("My research")).toBeVisible();
});
it("keeps management navigation separate from selection and hides saved presets in public mode", () => {
  savePreset({ id: "one", name: "Private preset", retrieval: { strategy: "hybrid", k: 5, candidate_k: 20, rrf_k: 60, lexical_ranker: "ts_rank_cd", bm25_k1: 1.2, bm25_b: 0.75, bm25_idf: "lucene", route_by_language: false, reranker: null } });
  const change = vi.fn(), manage = vi.fn();
  const { rerender } = render(<RetrievalPresetSelect profile={DEFAULT_SESSION_PROFILE} editable onChange={change} onManage={manage} />);
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "manage" } });
  expect(manage).toHaveBeenCalledOnce(); expect(change).not.toHaveBeenCalled();
  rerender(<RetrievalPresetSelect profile={DEFAULT_SESSION_PROFILE} editable={false} onChange={change} onManage={manage} />);
  expect(screen.queryByRole("option", { name: "Private preset" })).toBeNull();
  expect(screen.queryByRole("option", { name: "Manage presets…" })).toBeNull();
});

it("offers explicit dropdowns for all addable filters and uses returned section choices", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ issuers: [{ value: "NVDA", count: 1 }], languages: [{ value: "en", count: 1 }], years: [{ value: "2024", count: 1 }], forms: [{ value: "10-K", count: 1 }], sections: [{ value: "7", count: 1 }, { value: "unsectioned", count: 1 }] }), { status: 200 })));
  const change = vi.fn();
  render(<ConversationSettings profile={DEFAULT_SESSION_PROFILE} tab="filters" editable onChange={change} onTabChange={vi.fn()} onClose={vi.fn()} />);
  const sectionToggle = screen.getByRole("button", { name: "Show Sections choices" });
  await waitFor(() => expect(sectionToggle).toBeEnabled());
  for (const field of ["Companies", "Languages", "Fiscal years", "Forms", "Sections"]) expect(screen.getByRole("button", { name: `Show ${field} choices` })).toBeEnabled();
  fireEvent.click(sectionToggle);
  expect(sectionToggle).toHaveAttribute("aria-expanded", "true");
  const choices = screen.getByRole("group", { name: "Sections suggestions" });
  fireEvent.click(within(choices).getByRole("button", { name: "7" }));
  expect(change).toHaveBeenCalledWith({ sections: ["7"] });
  fireEvent.click(sectionToggle);
  expect(screen.queryByRole("group", { name: "Sections suggestions" })).toBeNull();
});

/** Valid server-supported values must pass native form checks and persist on submit. */
it("saves presets with 500 candidates and fractional BM25 values", () => {
  render(<RetrievalPresetManager />);
  const row = screen.getByRole("button", { name: "Balanced" }).closest("section")!;
  fireEvent.click(within(row).getByRole("button", { name: "Balanced" }));
  fireEvent.click(within(row).getByRole("button", { name: "Copy and edit" }));
  fireEvent.change(screen.getByLabelText("Preset name"), { target: { value: "Wide fractional search" } });
  for (const [label, value] of [["candidate_k", "500"], ["BM25 k1", "0.05"], ["BM25 b", "0.33"]]) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  const save = screen.getByRole("button", { name: "Save preset" });
  expect(save.closest("form")!.checkValidity()).toBe(true);
  fireEvent.click(save);
  expect(screen.getByRole("button", { name: "Wide fractional search" })).toBeVisible();
});

it("shows server policy guidance in public mode without local CPU advice", () => {
  render(<ConversationSettings profile={DEFAULT_SESSION_PROFILE} tab="limits" editable={false} onChange={vi.fn()} onTabChange={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByText("Question execution limits")).toBeVisible();
  expect(screen.queryByText(/CPU start:/)).not.toBeInTheDocument();
  expect(screen.queryByRole("combobox", { name: "Limit preset" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Advanced" })).toBeNull();
});
