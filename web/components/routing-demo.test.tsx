import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { RoutingDemo } from "./routing-demo";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("resolves the covered issuer example entirely with deterministic rules", () => {
  const { container } = render(<RoutingDemo locale="en" />);
  expect(screen.getByText("Nvidia revenue 2024")).toBeInTheDocument();
  expect(screen.getByText("issuer_covered_finance")).toBeInTheDocument();
  expect(container.querySelector('[data-step="classifier"]')).toHaveAttribute("data-state", "skipped");
  expect(container.querySelector('[data-step="scope"]')).toHaveAttribute("data-state", "active");
  expect(container.querySelector('[data-field="classifier"]')).toHaveTextContent("0");
  expect(container.querySelector('[data-field="outcome"]')).toHaveTextContent("continues to retrieval");
});

it("stops a role-play request at stage 0 with zero classifier decisions", () => {
  const { container } = render(<RoutingDemo locale="en" />);
  fireEvent.click(screen.getByRole("button", { name: "Role-play request" }));
  expect(screen.getByText("고양이와 대화하기")).toBeInTheDocument();
  expect(screen.getByText("roleplay_request")).toBeInTheDocument();
  expect(container.querySelector('[data-step="classifier"]')).toHaveAttribute("data-state", "skipped");
  expect(container.querySelector('[data-step="scope"]')).toHaveAttribute("data-state", "skipped");
  expect(container.querySelector('[data-field="classifier"]')).toHaveTextContent("0");
  expect(container.querySelector('[data-field="outcome"]')).toHaveTextContent("stage 0");
});

it.each([["Unresolved target", "SanDisk growth drivers"], ["Mixed targets", "Nvidia and UnknownCorp revenue"]] as const)(
  "keeps %s pending on the classifier without a fabricated scope",
  (tab, query) => {
    const { container } = render(<RoutingDemo locale="en" />);
    fireEvent.click(screen.getByRole("button", { name: tab }));
    expect(screen.getByText(query)).toBeInTheDocument();
    expect(screen.getByText(/Classifier assistance needed/)).toBeInTheDocument();
    expect(container.querySelector('[data-step="classifier"]')).toHaveAttribute("data-state", "pending");
    expect(container.querySelector('[data-step="scope"]')).toHaveAttribute("data-state", "pending");
    expect(container.querySelector('[data-step="rules"] code')).toBeNull();
    expect(container.querySelector('[data-field="classifier"]')).toHaveTextContent("pending");
    expect(container.querySelector('[data-field="outcome"]')).toHaveTextContent("awaits classifier");
    expect(screen.queryByText(/exist in the illustrative corpus|scope guidance ends the run/)).toBeNull();
  },
);

it("drops the follow-up back to unresolved when prior conversation is off", () => {
  const { container } = render(<RoutingDemo locale="en" />);
  fireEvent.click(screen.getByRole("button", { name: "Follow-up" }));
  expect(screen.getByText("filing_followup")).toBeInTheDocument();
  const toggle = screen.getByRole("checkbox", { name: "Use prior conversation" });
  expect(toggle).toBeChecked();
  fireEvent.click(toggle);
  expect(toggle).not.toBeChecked();
  expect(screen.queryByText("filing_followup")).toBeNull();
  expect(screen.getByText(/not used/)).toBeInTheDocument();
  expect(container.querySelector('[data-step="classifier"]')).toHaveAttribute("data-state", "pending");
  expect(container.querySelector('[data-step="scope"]')).toHaveAttribute("data-state", "pending");
});

it.each(["ko", "en"] as const)("renders localized labels in %s", (locale) => {
  const ko = locale === "ko";
  const { container } = render(<RoutingDemo locale={locale} />);
  expect(screen.getByText(ko ? "라우팅 미니 실험" : "Routing mini-lab")).toBeInTheDocument();
  expect(screen.getByText(ko ? "설명용 예시 — 실제 검색·모델 호출 없음" : "Illustrative examples — no search or model calls")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: ko ? "미확정 대상" : "Unresolved target" }));
  expect(screen.getByText(ko ? /보조 분류 필요/ : /Classifier assistance needed/)).toBeInTheDocument();
  expect(container.querySelector('[data-field="classifier"]')).toHaveTextContent(ko ? "대기" : "pending");
});

it("runs fully local — no fetch is invoked", () => {
  const fetchSpy = vi.fn();
  vi.stubGlobal("fetch", fetchSpy);
  render(<RoutingDemo locale="en" />);
  fireEvent.click(screen.getByRole("button", { name: "Mixed targets" }));
  fireEvent.click(screen.getByRole("button", { name: "Follow-up" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Use prior conversation" }));
  expect(fetchSpy).not.toHaveBeenCalled();
});
