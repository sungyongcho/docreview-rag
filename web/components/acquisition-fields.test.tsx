import { useState } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { AdminDocument } from "@/lib/types";
import { AcquisitionFields } from "./acquisition-fields";

afterEach(cleanup);

const documents = [
  { registry: "sec", issuer: "AAPL", issuer_name: "Apple Inc.", fiscal_year: 2024 },
  { registry: "sec", issuer: "NVDA", issuer_name: "NVIDIA Corporation", fiscal_year: 2023 },
  { registry: "dart", issuer: "005930", issuer_name: "삼성전자", fiscal_year: 2025 },
] as AdminDocument[];

/** Use the parent update and action pattern to verify the actual acquired request. */
function AcquisitionHarness({ onDownload = vi.fn(), initial = { registry: "sec" as const, identifiers: "NVDA", years: "2024" } }) {
  const [acquisition, setAcquisition] = useState<{ registry: "sec" | "dart"; identifiers: string; years: string }>(initial);
  const [valid, setValid] = useState(false);
  return <><AcquisitionFields acquisition={acquisition} onChange={setAcquisition} documents={documents} onValidityChange={setValid} /><button type="button" disabled={!valid} onClick={() => onDownload(acquisition)}>Acquire</button></>;
}

it("offers only actual companies from the selected registry and adds a name match", () => {
  const onDownload = vi.fn();
  render(<AcquisitionHarness onDownload={onDownload} />);
  const input = screen.getByLabelText("Tickers / stock codes");
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: "Apple" } });
  fireEvent.click(screen.getByRole("button", { name: "AAPL · Apple Inc." }));
  expect(screen.queryByRole("button", { name: "005930 · 삼성전자" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Acquire" }));
  expect(onDownload).toHaveBeenCalledWith({ registry: "sec", identifiers: "NVDA AAPL", years: "2024" });
});

it("commits a valid draft on blur before an acquisition action observes state", () => {
  const onDownload = vi.fn();
  render(<AcquisitionHarness onDownload={onDownload} />);
  const input = screen.getByLabelText("Tickers / stock codes");
  fireEvent.change(input, { target: { value: "brk.b" } });
  const action = screen.getByRole("button", { name: "Acquire" });
  expect(action).toBeEnabled();
  fireEvent.blur(input, { relatedTarget: action });
  fireEvent.click(action);
  expect(onDownload).toHaveBeenCalledWith({ registry: "sec", identifiers: "NVDA BRK.B", years: "2024" });
});

it("retains invalid company and year drafts and blocks acquisition until corrected", () => {
  const onDownload = vi.fn();
  render(<AcquisitionHarness onDownload={onDownload} />);
  const company = screen.getByLabelText("Tickers / stock codes");
  const year = screen.getByLabelText("Fiscal years");
  fireEvent.paste(company, { clipboardData: { getData: () => "NVDA,??" } });
  fireEvent.change(year, { target: { value: "2024-1900" } });
  fireEvent.blur(year);
  expect(company).toHaveValue("NVDA,??");
  expect(year).toHaveValue("2024-1900");
  const action = screen.getByRole("button", { name: "Acquire" });
  expect(action).toBeDisabled();
  fireEvent.click(action);
  expect(onDownload).not.toHaveBeenCalled();
  fireEvent.change(company, { target: { value: "AMD" } });
  fireEvent.keyDown(company, { key: "Enter" });
  expect(action).toBeDisabled();
  fireEvent.change(year, { target: { value: "2023-2025" } });
  fireEvent.keyDown(year, { key: "Enter" });
  expect(within(screen.getByLabelText("Selected Fiscal years")).getAllByRole("listitem")).toHaveLength(3);
  expect(action).toBeEnabled();
  fireEvent.click(action);
  expect(onDownload).toHaveBeenCalledWith({ registry: "sec", identifiers: "NVDA AMD", years: "2024 2023 2025" });
});

it("keeps incompatible codes on a registry change until deliberately removed", () => {
  const onDownload = vi.fn();
  render(<AcquisitionHarness onDownload={onDownload} />);
  fireEvent.click(screen.getByRole("button", { name: "DART" }));
  expect(screen.getByRole("button", { name: "Remove NVDA" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Acquire" })).toBeDisabled();
  const input = screen.getByLabelText("Tickers / stock codes");
  fireEvent.focus(input);
  expect(screen.getByRole("button", { name: "005930 · 삼성전자" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Remove NVDA" }));
  fireEvent.paste(input, { clipboardData: { getData: () => "005930,000660" } });
  fireEvent.click(screen.getByRole("button", { name: "Acquire" }));
  expect(onDownload).toHaveBeenCalledWith({ registry: "dart", identifiers: "005930 000660", years: "2024" });
});

it("never preselects suggested years and accepts positive four-digit years beyond the present", () => {
  render(<AcquisitionHarness initial={{ registry: "sec", identifiers: "NVDA", years: "" }} />);
  expect(screen.queryByLabelText("Selected Fiscal years")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Acquire" })).toBeDisabled();
  const input = screen.getByLabelText("Fiscal years");
  fireEvent.paste(input, { clipboardData: { getData: () => "0000,2024" } });
  expect(input).toHaveValue("0000,2024");
  expect(screen.getByRole("button", { name: "Acquire" })).toBeDisabled();
  fireEvent.change(input, { target: { value: "2099" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(screen.getByRole("button", { name: "Remove 2099" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Acquire" })).toBeEnabled();
});
