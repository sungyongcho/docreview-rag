import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Onboarding } from "./onboarding";

describe("onboarding", () => {
  afterEach(cleanup);

  it("walks through the public steps and closes on finish", () => {
    const close = vi.fn();
    render(<Onboarding onClose={close} />);

    expect(screen.getByText("Step 1 of 7")).toBeInTheDocument();
    for (let step = 0; step < 6; step += 1) fireEvent.click(screen.getByText("Next"));
    expect(screen.getByText("Step 7 of 7")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Finish"));

    expect(close).toHaveBeenCalledOnce();
  });

  it("advances after the highlighted real target is clicked", () => {
    const close = vi.fn();
    render(<><button data-tour="new-review" type="button">New review target</button><Onboarding onClose={close} /></>);

    fireEvent.click(screen.getByText("New review target"));

    expect(screen.getByText("Step 2 of 7")).toBeInTheDocument();
    expect(screen.getByText("Ask a grounded question")).toBeInTheDocument();
  });

  it("includes the local Operations target only when available", () => {
    render(<Onboarding onClose={vi.fn()} includeOperations />);
    expect(screen.getByText("Step 1 of 8")).toBeInTheDocument();
  });
});
