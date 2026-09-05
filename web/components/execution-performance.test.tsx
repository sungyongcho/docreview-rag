import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { I18nProvider, LOCALE_KEY } from "@/lib/i18n";
import type { ReviewExecution } from "@/lib/types";
import { ExecutionPerformance } from "./execution-performance";

const state: ReviewExecution = { node: "report", evidence: 5, relevant: 2, steps: 3, outcome: "completed" };

afterEach(() => { cleanup(); localStorage.clear(); });

/** Open the disclosure so checks inspect the actual accessible content. */
function showPerformance(data?: Record<string, unknown>, execution = state) {
  const result = render(<ExecutionPerformance data={data} state={execution} />);
  fireEvent.click(screen.getByText("Execution performance"));
  return result;
}

/** Find a named metric without depending on the surrounding grid. */
function fact(label: string) {
  return screen.getByText(label, { selector: "dt" }).parentElement!.querySelector("dd")!;
}

describe("Measured execution performance", () => {
  it("distinguishes submillisecond, zero, missing and invalid stage durations", () => {
    const { container } = showPerformance({ stages: [
      { node: "gate", status: "completed", elapsed_ms: 0.03 },
      { node: "route", status: "completed", elapsed_ms: 0 },
      { node: "retrieve", status: "completed", elapsed_ms: 3.84 },
      { node: "grade", status: "completed", elapsed_ms: null },
      { node: "check", status: "failed", elapsed_ms: Number.NaN },
      { node: "report", status: "completed", elapsed_ms: -1 },
    ] }, { ...state, elapsedMs: 0.2 });
    const table = screen.getByRole("table", { name: /Measured stage durations/ });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getAllByRole("cell").at(-1)!.textContent)).toEqual(["<1ms", "0ms", "3.84ms", "Not collected", "Not collected", "Not collected"]);
    expect(within(rows[0]).getByText("<1ms")).toHaveAttribute("title", "0.03ms");
    expect(fact("Request time")).toHaveTextContent("<1ms");
    const ascii = container.querySelector(".performance-ascii")!;
    expect(ascii).toHaveAttribute("aria-hidden", "true");
    expect(ascii.textContent!.split("\n")).toHaveLength(3);
    expect(ascii.textContent).toContain("[####################] 3.84ms");
    expect(ascii.textContent).not.toMatch(/NaN|Infinity|undefined|0s/);
  });

  it("preserves retries in collection order and excludes unmeasured start clocks from bars", () => {
    const { container } = showPerformance({ stages: [
      { node: "retrieve", status: "completed", elapsed_ms: 500 },
      { node: "grade", status: "completed", elapsed_ms: 1000 },
      { node: "retrieve", status: "running", phase: "start", elapsed_ms: null },
      { node: "retrieve", status: "completed", elapsed_ms: 250 },
      { node: "grade", status: "failed", elapsed_ms: 0 },
    ] });
    const table = screen.getByRole("table", { name: /Measured stage durations/ });
    expect(Array.from(table.querySelectorAll("tbody tr td:nth-child(2) code"), (node) => node.textContent)).toEqual(["retrieve", "grade", "retrieve", "retrieve", "grade"]);
    const lines = container.querySelector(".performance-ascii")!.textContent!.split("\n");
    expect(lines.map((line) => line.slice(0, 2))).toEqual(["01", "02", "04", "05"]);
    expect(lines[0]).toContain("[##########..........] 500ms");
    expect(lines[1]).toContain("[####################] 1s");
    expect(lines[2]).toContain("[#####...............] 250ms");
    expect(lines[3]).toContain("[ERR ");
    expect(lines[3]).toContain("[....................] 0ms");
  });

  it("keeps legacy records explicit and never infers attempts or device placement", () => {
    const { rerender } = showPerformance();
    for (const label of ["Request time", "Server execution", "Model calls / attempts", "CPU / GPU placement"]) expect(fact(label)).toHaveTextContent("Not collected");
    expect(screen.queryByRole("table")).toBeNull();
    rerender(<ExecutionPerformance state={state} data={{ model_calls: [
      { node: "grade", model: "local-model", input_tokens: 0, output_tokens: 0 },
      { node: "grade", model: "local-model", elapsed_ms: 1200, attempts: 2 },
    ] }} />);
    expect(fact("Model calls / attempts")).toHaveTextContent("2 / Not collected");
    expect(fact("CPU / GPU placement")).toHaveTextContent("Not collected");
    const rows = within(screen.getByRole("table", { name: /Measured model calls/ })).getAllByRole("row").slice(1);
    expect(within(rows[0]).getAllByRole("cell").map((cell) => cell.textContent).slice(2)).toEqual(["Not collected", "Not collected", "0", "0"]);
    expect(within(rows[1]).getAllByRole("cell").map((cell) => cell.textContent).slice(2)).toEqual(["1.2s", "2", "Not collected", "Not collected"]);
  });

  it("derives speed only from collected positive token counts and durations", () => {
    const { container } = showPerformance({ model_calls: [{ node: "grade", model: "test-model", attempts: 3, local_timings: [
      { eval_count: 50, eval_duration_ms: 2000, load_duration_ms: 0.08 },
      { eval_count: 0, eval_duration_ms: 20 },
      { eval_count: 10, eval_duration_ms: 0 },
      { eval_count: 10 },
    ] }] });
    fireEvent.click(screen.getByText(/Select relevant evidence · Provider timing breakdown/));
    const values = Array.from(container.querySelectorAll(".performance-timing-record"), (record) => within(record as HTMLElement).getByText("Generated tokens / speed", { selector: "dt" }).nextElementSibling!.textContent);
    expect(values).toEqual(["50 / 25 tok/s", "0 / Not collected", "10 / Not collected", "10 / Not collected"]);
    expect(screen.getByText("<1ms")).toBeVisible();
    expect(fact("Model calls / attempts")).toHaveTextContent("1 / 3");
  });

  it("uses received live measurements when stored execution data is absent", () => {
    showPerformance(undefined, { ...state, stageTimings: [{ node: "check", elapsed_ms: 84, status: "failed" }] });
    const table = screen.getByRole("table", { name: /Measured stage durations/ });
    expect(within(table).getByText("Verify answer and citations")).toBeVisible();
    expect(within(table).getByText("84ms")).toBeVisible();
    expect(fact("Model calls / attempts")).toHaveTextContent("Not collected");
  });

  it("keeps a zero-only measurement finite and explicitly reports recorded calls with no attempts", () => {
    const { container } = showPerformance({ stages: [{ node: "gate", status: "completed", elapsed_ms: 0 }], model_calls: [] });
    expect(container.querySelector(".performance-ascii")!.textContent).toContain("[....................] 0ms");
    expect(fact("Model calls / attempts")).toHaveTextContent("0 / 0");
  });

  it("localizes primary stage and status text while retaining technical identifiers", () => {
    localStorage.setItem(LOCALE_KEY, "ko");
    render(<I18nProvider><ExecutionPerformance state={state} data={{ stages: [{ node: "route", status: "completed", elapsed_ms: 1200 }], model_calls: [{ node: "grade", model: "ollama:qwen3:8b", elapsed_ms: 600 }] }} /></I18nProvider>);
    fireEvent.click(screen.getByText("실행 성능"));
    const stages = screen.getByRole("table", { name: /수집된 단계 소요 시간/ });
    expect(within(stages).getByText("공시 범위 결정")).toBeVisible();
    expect(within(stages).getByText("완료")).toBeVisible();
    expect(within(stages).getByText("route", { selector: "code" })).toBeVisible();
    expect(within(stages).getByText("completed", { selector: "code" })).toBeVisible();
    expect(screen.getByText("ollama:qwen3:8b")).toBeVisible();
    expect(screen.getByText("관련 근거 선택", { selector: "span" })).toBeVisible();
  });
});
