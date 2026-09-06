import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n";
import { ServiceHealthModal } from "./service-health-modal";

const handlers = {
  onRetry: vi.fn(),
  onReload: vi.fn(),
  onDismiss: vi.fn(),
  onOpenStatus: vi.fn(),
  onOpenBuild: vi.fn(),
};

describe("ServiceHealthModal", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("blocks API-down state and offers retry plus reload", () => {
    render(<ServiceHealthModal kind="api_down" visible checking={false} {...handlers} />);

    expect(screen.getByRole("dialog")).toHaveTextContent("DocReview RAG API is unavailable");
    expect(screen.queryByRole("button", { name: "Close database warning" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Try again/ }));
    fireEvent.click(screen.getByRole("button", { name: /Reload page/ }));
    expect(handlers.onRetry).toHaveBeenCalled();
    expect(handlers.onReload).toHaveBeenCalled();
  });

  it("explains DB degradation and opens the repair surface without retry looping", () => {
    render(<ServiceHealthModal kind="db_degraded" visible checking={false} degradedMessage="Schema drift detected." {...handlers} />);

    expect(screen.getByRole("dialog")).toHaveTextContent("Database is not ready");
    expect(screen.getByRole("dialog")).toHaveTextContent("Schema drift detected");
    expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Close database warning" }));
    fireEvent.click(screen.getByRole("button", { name: "Open System status" }));
    fireEvent.click(screen.getByRole("button", { name: "Open Build" }));
    expect(handlers.onDismiss).toHaveBeenCalled();
    expect(handlers.onOpenStatus).toHaveBeenCalled();
    expect(handlers.onOpenBuild).toHaveBeenCalled();
  });
});


it("explains preparation without a false database warning", () => {
  render(<ServiceHealthModal kind="preparation_needed" visible checking={false} degradedMessage="Schema matches the current ORM models." {...handlers} />);
  expect(screen.getByRole("dialog")).toHaveTextContent("Corpus preparation is needed");
  expect(screen.getByRole("dialog")).toHaveTextContent("The database is connected and its schema is compatible.");
  expect(screen.getByRole("dialog")).not.toHaveTextContent("Database is not ready");
  fireEvent.click(screen.getByRole("button", { name: "Close preparation notice" }));
  expect(handlers.onDismiss).toHaveBeenCalled();
  cleanup();
});

it("renders the preparation notice in Korean", () => {
  render(<I18nProvider><ServiceHealthModal kind="preparation_needed" visible checking={false} {...handlers} /></I18nProvider>);
  expect(screen.getByRole("dialog")).toHaveTextContent("문서 준비가 필요합니다");
  expect(screen.getByRole("dialog")).toHaveTextContent("DB가 연결되어 있고 스키마도 호환됩니다.");
  expect(screen.getByRole("dialog")).not.toHaveTextContent("DB 준비가 필요합니다");
  cleanup();
});

it.each(["en", "ko"])("wraps DB errors in closed terminal details (%s)", (locale) => {
  localStorage.setItem("docreview.locale", locale);
  const raw = "Schema mismatch: table 'chunks' missing columns. <script>example</script>";
  render(<I18nProvider><ServiceHealthModal kind="db_degraded" visible checking={false} degradedMessage={raw} {...handlers} /></I18nProvider>);
  const summary = screen.getByText(locale === "en" ? "Please review the error" : "에러를 확인해주세요");
  const details = summary.closest("details");
  expect(details).not.toHaveAttribute("open");
  expect(details?.querySelector("pre code")).toHaveTextContent(raw);
  expect(details?.querySelector("script")).toBeNull();
  fireEvent.click(summary);
  expect(details).toHaveAttribute("open");
  fireEvent.click(summary);
  expect(details).not.toHaveAttribute("open");
  cleanup(); localStorage.clear();
});
