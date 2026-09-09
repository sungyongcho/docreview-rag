import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DEFAULT_PROFILE, DEFAULT_SESSION_PROFILE, type DocumentFacets, type ReviewSessionDraft } from "@/lib/types";
import { I18nProvider } from "@/lib/i18n";
import { ConversationSettings } from "./conversation-settings";
import { RetainedPanel } from "./retained-panel";

const api = vi.hoisted(() => ({ getDocumentFacets: vi.fn(), getPublishedDocumentFacets: vi.fn() }));
vi.mock("@/lib/api", () => api);

const facets: DocumentFacets = {
  registries: [], issuers: [{ value: "AAPL", label: "AAPL · Apple Inc.", count: 1 }, { value: "005930", label: "005930 · 삼성전자", count: 1 }],
  languages: [{ value: "en", label: null, count: 1 }, { value: "ko", label: null, count: 1 }],
  years: [{ value: "2024", label: null, count: 2 }], forms: [{ value: "10-K", label: null, count: 1 }, { value: "사업보고서", label: null, count: 1 }],
  sections: [], parse_statuses: [], embedding_statuses: [], snapshots: [],
};
beforeEach(() => { api.getDocumentFacets.mockResolvedValue(facets); api.getPublishedDocumentFacets.mockResolvedValue(facets); });
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("edits only the current conversation policy and reads the next conversation's values", () => {
  const onChange = vi.fn();
  const props = { editable: true, onChange, onTabChange: vi.fn(), onClose: vi.fn() };
  const { rerender } = render(<ConversationSettings {...props} tab="limits" profile={DEFAULT_SESSION_PROFILE} />);
  expect(screen.getByRole("button", { name: "Run limits" })).toHaveAttribute("title", "DEV only");
  expect(screen.getByRole("button", { name: "Filters" }).querySelector(".development-badge")).toBeNull();
  fireEvent.change(screen.getByLabelText("Maximum wall clock seconds"), { target: { value: "240" } });
  expect(onChange).toHaveBeenCalledWith({ prompt_policy: { ...DEFAULT_SESSION_PROFILE.prompt_policy, workflow_budget: { ...DEFAULT_SESSION_PROFILE.prompt_policy.workflow_budget, max_wall_clock_s: 240 } } });
  rerender(<ConversationSettings {...props} tab="limits" profile={{ ...DEFAULT_SESSION_PROFILE, prompt_policy: { ...DEFAULT_SESSION_PROFILE.prompt_policy, workflow_budget: { ...DEFAULT_SESSION_PROFILE.prompt_policy.workflow_budget, max_wall_clock_s: 90 } } }} />);
  expect(screen.getByLabelText("Maximum wall clock seconds")).toHaveValue(90);
  fireEvent.keyDown(screen.getByRole("dialog", { name: "Conversation settings" }), { key: "Escape" });
  expect(props.onClose).toHaveBeenCalledOnce();
});

it("uses the API candidate and conversation fusion limits for custom retrieval", () => {
  render(<ConversationSettings tab="retrieval" editable profile={{ ...DEFAULT_SESSION_PROFILE, retrieval_preset: "custom", custom_retrieval: DEFAULT_PROFILE }} onChange={vi.fn()} onTabChange={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByLabelText("candidate_k")).toHaveAttribute("max", "500");
  expect(screen.getByLabelText("candidate_k")).toHaveAttribute("min", String(DEFAULT_PROFILE.k));
  expect(screen.getByLabelText("RRF k")).toHaveAttribute("max", "10000");
});

it("translates every conversation settings tab in the Korean interface", () => {
  render(<I18nProvider><ConversationSettings tab="limits" editable profile={DEFAULT_SESSION_PROFILE} onChange={vi.fn()} onTabChange={vi.fn()} onClose={vi.fn()} /></I18nProvider>);
  for (const name of ["필터", "검색", "근거", "실행 한도"]) expect(screen.getByRole("button", { name })).toBeInTheDocument();
});

it("keeps allowed filters but hides developer controls in public mode", async () => {
  render(<ConversationSettings tab="limits" editable={false} profile={DEFAULT_SESSION_PROFILE} onChange={vi.fn()} onTabChange={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByLabelText("Companies")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Run limits" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Maximum wall clock seconds")).not.toBeInTheDocument();
  expect(document.querySelector(".conversation-settings-sections .development-badge")).toBeNull();
  await screen.findByRole("button", { name: "English (en)" });
  expect(api.getPublishedDocumentFacets).toHaveBeenCalledWith(undefined, expect.any(AbortSignal));
  expect(api.getDocumentFacets).not.toHaveBeenCalled();
});

/** Keep the real patch merge semantics used by the conversation owner. */
function FilterHarness({ profile = DEFAULT_SESSION_PROFILE, onPatch = vi.fn(), onValidityChange }: { profile?: ReviewSessionDraft; onPatch?: (patch: Partial<ReviewSessionDraft>) => void; onValidityChange?: (valid: boolean) => void }) {
  const [current, setCurrent] = useState(profile);
  return <ConversationSettings tab="filters" editable profile={current} onChange={(patch) => { onPatch(patch); setCurrent((value) => ({ ...value, ...patch })); }} onTabChange={vi.fn()} onClose={vi.fn()} onValidityChange={onValidityChange} />;
}

it("uses complete corpus choices for company names, language, years, forms, and removable chips", async () => {
  const onPatch = vi.fn();
  render(<FilterHarness onPatch={onPatch} />);
  await screen.findByRole("button", { name: "English (en)" });
  const companies = screen.getByLabelText("Companies");
  fireEvent.focus(companies);
  fireEvent.change(companies, { target: { value: "Apple" } });
  fireEvent.click(screen.getByRole("button", { name: "AAPL · Apple Inc." }));
  expect(onPatch).toHaveBeenLastCalledWith({ issuers: ["AAPL"] });
  fireEvent.click(within(screen.getByRole("group", { name: "Quick add Languages" })).getByRole("button", { name: "English (en)" }));
  expect(onPatch).toHaveBeenLastCalledWith({ languages: ["en"] });
  fireEvent.click(within(screen.getByRole("group", { name: "Quick add Fiscal years" })).getByRole("button", { name: "2024" }));
  expect(onPatch).toHaveBeenLastCalledWith({ fiscal_years: [2024] });
  fireEvent.click(within(screen.getByRole("group", { name: "Quick add Forms" })).getByRole("button", { name: "10-K" }));
  expect(onPatch).toHaveBeenLastCalledWith({ forms: ["10-K"] });
  fireEvent.click(screen.getByRole("button", { name: "Remove AAPL · Apple Inc." }));
  expect(onPatch).toHaveBeenLastCalledWith({ issuers: [] });
  const sections = screen.getByLabelText("Sections");
  fireEvent.change(sections, { target: { value: "7 7A unsectioned" } });
  expect(sections).toHaveValue("7 7A unsectioned");
  fireEvent.keyDown(sections, { key: "Enter" });
  expect(onPatch).toHaveBeenLastCalledWith({ sections: ["7", "7A", null] });
});

it("ignores an older facet response and retains incompatible filters until explicit removal", async () => {
  let resolveOld!: (value: DocumentFacets) => void;
  let resolveNew!: (value: DocumentFacets) => void;
  api.getDocumentFacets.mockReturnValueOnce(new Promise<DocumentFacets>((resolve) => { resolveOld = resolve; })).mockReturnValueOnce(new Promise<DocumentFacets>((resolve) => { resolveNew = resolve; }));
  const onChange = vi.fn();
  const props = { tab: "filters" as const, editable: true, onChange, onTabChange: vi.fn(), onClose: vi.fn() };
  const profile = { ...DEFAULT_SESSION_PROFILE, corpus_scope: "sec" as const, issuers: ["AAPL"], languages: ["en" as const], fiscal_years: [2024], forms: ["10-K"] };
  const { rerender } = render(<ConversationSettings {...props} profile={profile} />);
  const oldSignal = api.getDocumentFacets.mock.calls[0][1] as AbortSignal;
  rerender(<ConversationSettings {...props} profile={{ ...profile, corpus_scope: "dart" }} />);
  expect(oldSignal.aborted).toBe(true);
  expect(api.getDocumentFacets).toHaveBeenLastCalledWith("dart", expect.any(AbortSignal));
  const dart = { ...facets, issuers: [facets.issuers[1]], languages: [facets.languages[1]], years: [{ value: "2025", label: null, count: 1 }], forms: [facets.forms[1]] };
  await act(async () => { resolveNew(dart); });
  await act(async () => { resolveOld(facets); });
  expect(onChange).not.toHaveBeenCalled();
  expect(screen.getAllByText("Outside this scope")).toHaveLength(4);
  fireEvent.focus(screen.getByLabelText("Companies"));
  expect(screen.getByRole("button", { name: "005930 · 삼성전자" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "AAPL · Apple Inc." })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Remove unavailable selections" }));
  expect(onChange).toHaveBeenCalledWith({ issuers: [], languages: [], fiscal_years: [], forms: [] });
});

it("reports failed or invalid facets and retries without clearing saved filters", async () => {
  api.getDocumentFacets.mockResolvedValueOnce({}).mockResolvedValueOnce(facets);
  const onPatch = vi.fn();
  render(<FilterHarness profile={{ ...DEFAULT_SESSION_PROFILE, issuers: ["AAPL"] }} onPatch={onPatch} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load available filters.");
  expect(screen.getByLabelText("Companies")).toBeDisabled();
  expect(onPatch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByRole("button", { name: "English (en)" });
  expect(screen.getByLabelText("Companies")).toBeEnabled();
  expect(screen.getByRole("button", { name: "Remove AAPL · Apple Inc." })).toBeInTheDocument();
});

it("reports every invalid draft without mutating saved filters until all fields are corrected", async () => {
  const onPatch = vi.fn();
  const onValidityChange = vi.fn();
  render(<FilterHarness profile={{ ...DEFAULT_SESSION_PROFILE, issuers: ["AAPL"] }} onPatch={onPatch} onValidityChange={onValidityChange} />);
  await screen.findByRole("button", { name: "English (en)" });
  const company = screen.getByLabelText("Companies");
  const years = screen.getByLabelText("Fiscal years");
  const forms = screen.getByLabelText("Forms");
  for (const field of [company, years, forms]) {
    fireEvent.change(field, { target: { value: "unknown" } });
    fireEvent.blur(field);
    expect(field).toHaveValue("unknown");
  }
  expect(onValidityChange).toHaveBeenLastCalledWith(false);
  expect(onPatch).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Remove AAPL · Apple Inc." })).toBeInTheDocument();
  fireEvent.change(company, { target: { value: "" } });
  expect(onValidityChange).toHaveBeenLastCalledWith(false);
  fireEvent.change(years, { target: { value: "2024" } });
  fireEvent.keyDown(years, { key: "Enter" });
  expect(onPatch).toHaveBeenLastCalledWith({ fiscal_years: [2024] });
  expect(onValidityChange).toHaveBeenLastCalledWith(false);
  fireEvent.change(forms, { target: { value: "" } });
  expect(onValidityChange).toHaveBeenLastCalledWith(true);
  expect(onPatch).toHaveBeenCalledTimes(1);
});

it("restores validity after explicitly removing an unavailable selected filter", async () => {
  const onValidityChange = vi.fn();
  const onPatch = vi.fn();
  render(<FilterHarness profile={{ ...DEFAULT_SESSION_PROFILE, issuers: ["UNKNOWN"] }} onPatch={onPatch} onValidityChange={onValidityChange} />);
  await screen.findByRole("button", { name: "English (en)" });
  await waitFor(() => expect(onValidityChange).toHaveBeenLastCalledWith(false));
  expect(onPatch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Remove UNKNOWN" }));
  expect(onValidityChange).toHaveBeenLastCalledWith(true);
  expect(onPatch).toHaveBeenCalledWith({ issuers: [] });
});

it("explains draft discard and releases the sending guard after the editor closes", async () => {
  const onValidityChange = vi.fn();
  const onChange = vi.fn();
  const { unmount } = render(<ConversationSettings tab="filters" editable profile={{ ...DEFAULT_SESSION_PROFILE, issuers: ["AAPL"] }} onChange={onChange} onTabChange={vi.fn()} onClose={vi.fn()} onValidityChange={onValidityChange} />);
  await screen.findByRole("button", { name: "English (en)" });
  fireEvent.change(screen.getByLabelText("Companies"), { target: { value: "unknown" } });
  expect(onValidityChange).toHaveBeenLastCalledWith(false);
  expect(screen.getByRole("status")).toHaveTextContent("Switching tabs or closing this panel discards unfinished entries; selected filters stay unchanged.");
  unmount();
  expect(onValidityChange).toHaveBeenLastCalledWith(true);
  expect(onChange).not.toHaveBeenCalled();
});

it("traps drawer focus, protects the background, and restores the opener on close", () => {
  const onClose = vi.fn();
  const opener = document.createElement("button");
  document.body.append(opener);
  opener.focus();
  const { unmount } = render(<ConversationSettings tab="limits" editable profile={DEFAULT_SESSION_PROFILE} onChange={vi.fn()} onTabChange={vi.fn()} onClose={onClose} />);
  const dialog = screen.getByRole("dialog", { name: "Conversation settings" });
  const close = screen.getByRole("button", { name: "Close conversation settings" });
  const last = screen.getByRole("button", { name: "Restore setting defaults" });
  expect(dialog).toHaveAttribute("aria-modal", "true");
  expect(close).toHaveFocus();
  expect(opener).toHaveAttribute("inert");
  expect(document.body.style.overflow).toBe("hidden");
  fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
  expect(last).toHaveFocus();
  fireEvent.keyDown(last, { key: "Tab" });
  expect(close).toHaveFocus();
  opener.focus();
  expect(close).toHaveFocus();
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(onClose).toHaveBeenCalledOnce();
  unmount();
  expect(opener).not.toHaveAttribute("inert");
  expect(document.body.style.overflow).toBe("");
  expect(opener).toHaveFocus();
  opener.remove();
});

it("hides a retained drawer without losing drafts, refetching facets, or handling hidden keys", async () => {
  const onClose = vi.fn();
  const onValidityChange = vi.fn();
  const content = <ConversationSettings tab="filters" editable profile={DEFAULT_SESSION_PROFILE} onChange={vi.fn()} onTabChange={vi.fn()} onClose={onClose} onValidityChange={onValidityChange} />;
  const { rerender } = render(<><button>Other workspace</button><RetainedPanel active>{content}</RetainedPanel></>);
  await screen.findByRole("button", { name: "English (en)" });
  const company = screen.getByLabelText("Companies");
  fireEvent.change(company, { target: { value: "unfinished" } });
  expect(onValidityChange).toHaveBeenLastCalledWith(false);
  rerender(<><button>Other workspace</button><RetainedPanel active={false}>{content}</RetainedPanel></>);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  const other = screen.getByRole("button", { name: "Other workspace" });
  other.focus();
  fireEvent.keyDown(other, { key: "Escape" });
  expect(other).toHaveFocus();
  expect(onClose).not.toHaveBeenCalled();
  rerender(<><button>Other workspace</button><RetainedPanel active>{content}</RetainedPanel></>);
  expect(screen.getByLabelText("Companies")).toBe(company);
  expect(company).toHaveValue("unfinished");
  expect(api.getDocumentFacets).toHaveBeenCalledTimes(1);
  expect(onValidityChange).toHaveBeenLastCalledWith(false);
});


it("offers one stable evidence reduction without repeatedly halving the applied limit", () => {
  const onChange = vi.fn();
  const profile = structuredClone(DEFAULT_SESSION_PROFILE);
  const props = { editable: true, speed: 10.2, onChange, onTabChange: vi.fn(), onClose: vi.fn() };
  const { rerender } = render(<ConversationSettings {...props} tab="evidence" profile={profile} />);
  fireEvent.click(screen.getByRole("button", { name: "Reduce evidence: 12000 → 8000 characters" }));
  expect(onChange).toHaveBeenCalledExactlyOnceWith({ prompt_policy: { ...profile.prompt_policy, max_context_chars: 8000 } });
  const applied = { ...profile, prompt_policy: { ...profile.prompt_policy, max_context_chars: 8000 } };
  rerender(<ConversationSettings {...props} tab="evidence" profile={applied} />);
  expect(screen.queryByRole("button", { name: /Reduce evidence:/ })).toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent("No further reduction is suggested");
  rerender(<ConversationSettings {...props} tab="limits" profile={applied} />);
  rerender(<ConversationSettings {...props} tab="evidence" profile={applied} />);
  expect(screen.queryByRole("button", { name: /Reduce evidence:/ })).toBeNull();
  expect(onChange).toHaveBeenCalledOnce();
});

it("preserves a smaller evidence limit and leaves manual changes available", () => {
  const profile = { ...DEFAULT_SESSION_PROFILE, prompt_policy: { ...DEFAULT_SESSION_PROFILE.prompt_policy, max_context_chars: 1000 } };
  const onChange = vi.fn();
  render(<ConversationSettings tab="evidence" editable speed={10.2} profile={profile} onChange={onChange} onTabChange={vi.fn()} onClose={vi.fn()} />);
  expect(screen.queryByRole("button", { name: /Reduce evidence:/ })).toBeNull();
  expect(screen.getByLabelText("Maximum evidence characters")).toHaveValue(1000);
  expect(onChange).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Maximum evidence characters"), { target: { value: "6000" } });
  expect(onChange).toHaveBeenCalledExactlyOnceWith({ prompt_policy: { ...profile.prompt_policy, max_context_chars: 6000 } });
});


it("saves and resets only future chat search defaults without modifying the active conversation", async () => {
  const { loadDefaultProfile, saveDefaultProfile } = await import("@/lib/storage");
  window.localStorage.clear();
  const original = { ...DEFAULT_SESSION_PROFILE, prompt_policy: { ...DEFAULT_SESSION_PROFILE.prompt_policy, additional_instructions: "Keep my policy" } };
  saveDefaultProfile(original);
  const onChange = vi.fn();
  render(<ConversationSettings tab="retrieval" editable profile={{ ...DEFAULT_SESSION_PROFILE, retrieval_preset: "custom", custom_retrieval: { ...DEFAULT_PROFILE, k: 9 } }} onChange={onChange} onTabChange={vi.fn()} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Save as new-chat search defaults" }));
  expect(loadDefaultProfile().custom_retrieval?.k).toBe(9);
  expect(loadDefaultProfile().prompt_policy).toEqual(original.prompt_policy);
  expect(onChange).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Reset new-chat search defaults" }));
  expect(loadDefaultProfile().retrieval_preset).toBe("balanced");
  expect(loadDefaultProfile().prompt_policy).toEqual(original.prompt_policy);
  expect(onChange).not.toHaveBeenCalled();
});
