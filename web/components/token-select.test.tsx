import { useState } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { TokenSelect } from "./token-select";

afterEach(cleanup);

/** Exercise real controlled updates rather than asserting an implementation-only parser. */
function Field({ custom = true, onValidityChange = vi.fn() }: { custom?: boolean; onValidityChange?: (valid: boolean) => void }) {
  const [values, setValues] = useState<string[]>([]);
  return <TokenSelect label="Companies" values={values} onChange={setValues} options={[{ value: "AAPL", label: "AAPL · Apple Inc." }, { value: "MSFT", label: "MSFT · Microsoft Corporation" }]}
    parseCustom={custom ? (value) => /^[A-Za-z][A-Za-z0-9.-]*$/.test(value) ? [value.toUpperCase()] : null : undefined}
    onValidityChange={onValidityChange} />;
}

it("retains an editing draft and commits several entries with delimiters, paste, and blur", () => {
  render(<Field />);
  const input = screen.getByLabelText("Companies");
  fireEvent.change(input, { target: { value: "nvda amd" } });
  expect(input).toHaveValue("nvda amd");
  expect(screen.queryByLabelText("Selected Companies")).not.toBeInTheDocument();
  fireEvent.keyDown(input, { key: "," });
  expect(input).toHaveValue("");
  expect(screen.getByRole("button", { name: "Remove NVDA" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Remove AMD" })).toBeInTheDocument();
  fireEvent.paste(input, { clipboardData: { getData: () => "AMD,brk.b\nBRK-B" } });
  expect(within(screen.getByLabelText("Selected Companies")).getAllByRole("listitem")).toHaveLength(4);
  fireEvent.change(input, { target: { value: "TSLA" } });
  fireEvent.blur(input);
  expect(screen.getByRole("button", { name: "Remove TSLA" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Remove AMD" }));
  expect(screen.queryByRole("button", { name: "Remove AMD" })).not.toBeInTheDocument();
  expect(input).toHaveFocus();
});

it("keeps an invalid paste intact without committing the valid subset", () => {
  const onValidityChange = vi.fn();
  render(<Field onValidityChange={onValidityChange} />);
  const input = screen.getByLabelText("Companies");
  fireEvent.paste(input, { clipboardData: { getData: () => "NVDA,???" } });
  expect(input).toHaveValue("NVDA,???");
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByRole("alert")).toBeInTheDocument();
  expect(screen.queryByLabelText("Selected Companies")).not.toBeInTheDocument();
  expect(onValidityChange).toHaveBeenLastCalledWith(false);
  fireEvent.change(input, { target: { value: "NVDA" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(onValidityChange).toHaveBeenLastCalledWith(true);
  expect(screen.getByRole("button", { name: "Remove NVDA" })).toBeInTheDocument();
});

it("searches names, supports keyboard suggestions, and preserves the underlying code", () => {
  render(<Field custom={false} />);
  const input = screen.getByLabelText("Companies");
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: "Apple" } });
  const suggestion = within(screen.getByRole("group", { name: "Companies suggestions" })).getByRole("button", { name: "AAPL · Apple Inc." });
  expect(screen.queryByRole("button", { name: "MSFT · Microsoft Corporation" })).not.toBeInTheDocument();
  fireEvent.keyDown(input, { key: "ArrowDown" });
  expect(suggestion).toHaveFocus();
  fireEvent.click(suggestion);
  expect(input).toHaveFocus();
  expect(input).toHaveValue("");
  expect(screen.getByRole("button", { name: "Remove AAPL · Apple Inc." })).toBeInTheDocument();
});

it("moves focus into suggestions when ArrowDown reopens an escaped list", () => {
  render(<Field custom={false} />);
  const input = screen.getByLabelText("Companies");
  fireEvent.focus(input);
  fireEvent.keyDown(input, { key: "Escape" });
  expect(screen.queryByRole("group", { name: "Companies suggestions" })).not.toBeInTheDocument();
  fireEvent.keyDown(input, { key: "ArrowDown" });
  expect(screen.getByRole("button", { name: "AAPL · Apple Inc." })).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
  expect(screen.getByRole("button", { name: "MSFT · Microsoft Corporation" })).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  expect(input).toHaveFocus();
  fireEvent.keyDown(input, { key: "ArrowDown" });
  expect(screen.getByRole("button", { name: "AAPL · Apple Inc." })).toHaveFocus();
});
