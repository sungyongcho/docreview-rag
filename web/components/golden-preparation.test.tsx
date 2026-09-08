import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { GoldenPreparation } from "./golden-preparation";
import { checkEvaluationPreparation, getGoldenSuites, getGoldenRevisions } from "@/lib/api";
import { DEFAULT_PROFILE, type EvaluationPreparation, type EvaluationRequest } from "@/lib/types";

vi.mock("@/lib/api", () => ({ checkEvaluationPreparation: vi.fn(), getGoldenSuites: vi.fn(), getGoldenRevisions: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const request: EvaluationRequest = { suite_id: "dart-ko", golden_revision_id: null, mode: "quick", profile: DEFAULT_PROFILE, target_tokens: [1024], strategies: ["hybrid"], lexical_rankers: ["bm25"] };
const ready: EvaluationPreparation = { suite_id: "dart-ko", kind: "builtin", state: "ready", verification_status: "pending_review", source_checks: [], blockers: [], next_step: null };

it("keeps pending human review separate from executable source readiness", async () => {
  vi.mocked(checkEvaluationPreparation).mockResolvedValue(ready);
  const onChecked = vi.fn();
  render(<GoldenPreparation request={request} onChecked={onChecked} />);
  expect(await screen.findByText("Ready to evaluate")).toBeVisible();
  expect(screen.getByText("Pending review")).toBeVisible();
  expect(screen.getByText("Built-in golden set")).toBeVisible();
  expect(screen.queryByText("Verified")).toBeNull();
  expect(onChecked).toHaveBeenCalledWith(ready);
});

it("reports an exact missing original and rechecks the selected revision", async () => {
  vi.mocked(checkEvaluationPreparation).mockResolvedValue({ ...ready, kind: "user", state: "source_missing", next_step: "filings", blockers: ["Samsung original missing"], source_checks: [{ golden_document_id: "005930-FY2024", registry: "dart", issuer: "005930", fiscal_year: 2024, filing_id: "20250311001085", document_id: null, state: "source_missing", detail: "Missing", company_name: "Samsung Electronics" }] });
  const onOpenSources = vi.fn();
  render(<GoldenPreparation request={{ ...request, golden_revision_id: 5 }} onOpenSources={onOpenSources} />);
  await waitFor(() => expect(screen.getAllByText("Originals required").length).toBeGreaterThan(0));
  expect(screen.getByText("User golden set")).toBeVisible();
  fireEvent.click(screen.getByText("Required originals and preparation details"));
  expect(screen.getByRole("group", { name: "Samsung Electronics" })).toBeVisible();
  expect(screen.getByText("FY2024")).toBeVisible();
  expect(screen.queryByText("20250311001085")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "FY2024: Originals required" }));
  expect(onOpenSources).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "Check updated status" }));
  await waitFor(() => expect(checkEvaluationPreparation).toHaveBeenCalledTimes(2));
  expect(vi.mocked(checkEvaluationPreparation).mock.calls[1][0].golden_revision_id).toBe(5);
});

it("uses one filename selector and forwards the exact user dataset identity", async () => {
  const { PipelineGoldenPicker } = await import("./golden-preparation");
  const { CANNED_SUITES } = await import("@/lib/canned");
  const onSelect = vi.fn();
  vi.mocked(getGoldenSuites).mockResolvedValue(CANNED_SUITES);
  vi.mocked(getGoldenRevisions).mockImplementation(async suite => suite === "sec-en" ? [{ revision_id: 77, suite_id: "sec-en", filename: "custom.json", status: "draft", version: 1, payload: [], sha256: "a".repeat(64), parent_id: null, created_at: "2026-09-08T00:00:00Z", updated_at: "2026-09-08T00:00:00Z" }] : []);
  vi.mocked(checkEvaluationPreparation).mockResolvedValue({ ...ready, suite_id: "sec-en" });
  render(<PipelineGoldenPicker request={{ ...request, suite_id: "sec-en" }} onSelect={onSelect} onManage={vi.fn()} action={<button>Run quick evaluation</button>} />);
  await screen.findByRole("option", { name: "custom.json" });
  expect(screen.getAllByRole("combobox")).toHaveLength(1);
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "file:77" } });
  expect(onSelect).toHaveBeenCalledWith("sec-en", 77);
  const manage = screen.getByRole("button", { name: "Manage golden sets" });
  expect(manage.nextElementSibling).toHaveTextContent("Run quick evaluation");
});
