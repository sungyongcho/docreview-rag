import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ScopeDemo } from "./scope-demo";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it.each(["en", "ko"] as const)("keeps both sources in scope when the question renders in %s", (lang) => {
  const { container } = render(<ScopeDemo locale="en" />);
  fireEvent.change(screen.getByRole("combobox", { name: "Question language" }), { target: { value: lang } });
  expect(screen.getByText(lang === "ko" ? "모든 기업의 매출을 비교해 주세요" : "Compare all available companies revenue")).toBeInTheDocument();
  expect(container.querySelectorAll('.scope-card[data-state="included"]')).toHaveLength(2);
  expect(container.querySelector('[data-field="included"]')).toHaveTextContent("2 / 2");
});

it.each([
  ["sec", "NVIDIA", "Samsung"],
  ["dart", "Samsung", "NVIDIA"],
] as const)("selecting %s excludes only the other source's filing", (source, kept, dropped) => {
  const { container } = render(<ScopeDemo locale="en" />);
  const card = (name: string) => [...container.querySelectorAll(".scope-card")].find((c) => c.textContent?.includes(name));
  fireEvent.change(screen.getByRole("combobox", { name: "Source" }), { target: { value: source } });
  expect(card(kept)).toHaveAttribute("data-state", "included");
  expect(card(dropped)).toHaveAttribute("data-state", "excluded");
  expect(container.querySelector('[data-field="included"]')).toHaveTextContent("1 / 2");
  fireEvent.change(screen.getByRole("combobox", { name: "Question language" }), { target: { value: "ko" } });
  expect(card(kept)).toHaveAttribute("data-state", "included");
  expect(card(dropped)).toHaveAttribute("data-state", "excluded");
});

it("runs fully local — no fetch is invoked", () => {
  const fetchSpy = vi.fn();
  vi.stubGlobal("fetch", fetchSpy);
  render(<ScopeDemo locale="ko" />);
  fireEvent.change(screen.getByRole("combobox", { name: "질문 언어" }), { target: { value: "ko" } });
  fireEvent.change(screen.getByRole("combobox", { name: "소스" }), { target: { value: "sec" } });
  expect(fetchSpy).not.toHaveBeenCalled();
});
