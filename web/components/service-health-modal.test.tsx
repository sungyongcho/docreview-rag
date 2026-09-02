import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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

    expect(screen.getByRole("dialog")).toHaveTextContent("DocReview API is unavailable");
    expect(screen.queryByRole("button", { name: "Close database warning" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Try again/ }));
    fireEvent.click(screen.getByRole("button", { name: /Reload page/ }));
    expect(handlers.onRetry).toHaveBeenCalled();
    expect(handlers.onReload).toHaveBeenCalled();
  });

  it("explains DB degradation and opens the repair surface without retry looping", () => {
    render(<ServiceHealthModal kind="db_degraded" visible checking={false} degradedMessage="12 chunks still need embeddings." {...handlers} />);

    expect(screen.getByRole("dialog")).toHaveTextContent("Database is not ready");
    expect(screen.getByRole("dialog")).toHaveTextContent("12 chunks still need embeddings");
    expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Close database warning" }));
    fireEvent.click(screen.getByRole("button", { name: "Open System status" }));
    fireEvent.click(screen.getByRole("button", { name: "Open Build" }));
    expect(handlers.onDismiss).toHaveBeenCalled();
    expect(handlers.onOpenStatus).toHaveBeenCalled();
    expect(handlers.onOpenBuild).toHaveBeenCalled();
  });
});
