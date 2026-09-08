import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { GoldenQuestionEditor } from "./golden-question-editor";
import { getAdminDocuments, getGoldenEvidence } from "@/lib/api";

vi.mock("@/lib/api", () => ({ getAdminDocuments: vi.fn(), getGoldenEvidence: vi.fn() }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const empty = { id: "draft-1", question: "", category: null, answers: [], reference_answer: "", expected_label: null, tags: [], note: "" };
function Host({ initial = empty, save = vi.fn() }: { initial?: Record<string, unknown>; save?: (json: string) => void }) {
  const [json, setJson] = useState(JSON.stringify(initial));
  return <GoldenQuestionEditor filename="custom.json" registry="sec" json={json} readOnly={false} dirty busy={false} error="" issues={[]} onChange={setJson} onSave={() => save(json)} onBack={vi.fn()} />;
}
it("allows a blank draft, starts without answerability, and uses multilingual tag chips", () => {
  const save = vi.fn(); render(<Host save={save} />);
  expect(screen.getByRole("button", { name: "Evidence available" })).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByRole("button", { name: "No evidence" })).toHaveAttribute("aria-pressed", "false");
  expect(screen.queryByLabelText("Reference answer")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  expect(JSON.parse(save.mock.calls[0][0]).question).toBe("");
  fireEvent.click(screen.getByText("Classification, tags and review note"));
  const input = screen.getByPlaceholderText("Korean or English tag · Enter to add");
  for (let i = 0; i < 2; i++) { fireEvent.change(input, { target: { value: " 메모리 위험 " } }); fireEvent.keyDown(input, { key: "Enter" }); }
  expect(screen.getAllByRole("button", { name: "Remove tag 메모리 위험" })).toHaveLength(1);
});
it("confirms before removing authored evidence and hides internal verdict inputs", async () => {
  render(<Host initial={{ ...empty, category: "simple_lookup", expected_label: "SUPPORTED", reference_answer: "42", answers: [{ doc_id: "doc", source_sha256: "a".repeat(64), start_char: 1, end_char: 2 }] }} />);
  fireEvent.click(screen.getByRole("button", { name: "No evidence" }));
  expect(screen.getByRole("dialog")).toBeVisible(); fireEvent.click(screen.getByRole("button", { name: "Cancel" })); expect(screen.getByLabelText("Reference answer")).toHaveValue("42");
  fireEvent.click(screen.getByRole("button", { name: "No evidence" }));
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  await waitFor(() => expect(screen.queryByLabelText("Reference answer")).toBeNull());
  expect(screen.queryByLabelText("Expected label")).toBeNull();
});
it("selects exact server source coordinates and prevents duplicate evidence", async () => {
  vi.mocked(getAdminDocuments).mockResolvedValue({ documents: [{ doc_id: "doc", issuer: "NVDA", fiscal_year: 2024, form: "10-K", chunk_count: 2 }], next_cursor: null } as never);
  const chunk = { chunk_id: 5, doc_id: "doc", source_sha256: "a".repeat(64), start_char: 150, end_char: 300, item: "7", kind: "text", body: "Exact evidence text", citation: "NVDA FY2024" };
  vi.mocked(getGoldenEvidence).mockResolvedValue({ chunks: [chunk], next_after: null });
  const save = vi.fn(); render(<Host initial={{ ...empty, category: "simple_lookup", expected_label: "SUPPORTED" }} save={save} />);
  fireEvent.click(screen.getByRole("button", { name: "Select evidence from documents" }));
  fireEvent.click(await screen.findByRole("button", { name: /NVDA · FY2024/ }));
  await screen.findByText("Exact evidence text");
  fireEvent.click(screen.getByRole("button", { name: "Use this evidence" }));
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  expect(JSON.parse(save.mock.calls[0][0]).answers).toEqual([{ doc_id: "doc", source_sha256: "a".repeat(64), start_char: 150, end_char: 300 }]);
  fireEvent.click(screen.getByRole("button", { name: "Select evidence from documents" }));
  fireEvent.click(await screen.findByRole("button", { name: /NVDA · FY2024/ }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Already selected" })).toBeDisabled());
});
