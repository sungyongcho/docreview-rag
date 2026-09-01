import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ServiceHealthModal } from "./service-health-modal";

const handlers = {
  onRetry: vi.fn(),
  onReload: vi.fn(),
  onDismiss: vi.fn(),
  onOpenStatus: vi.fn(),
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

  it("lets the user dismiss DB degradation or open status", () => {
    render(<ServiceHealthModal kind="db_degraded" visible checking={false} {...handlers} />);

    expect(screen.getByRole("dialog")).toHaveTextContent("Database is not ready");
    fireEvent.click(screen.getByRole("button", { name: "Close database warning" }));
    fireEvent.click(screen.getByRole("button", { name: "Open System status" }));
    expect(handlers.onDismiss).toHaveBeenCalled();
    expect(handlers.onOpenStatus).toHaveBeenCalled();
  });
});
