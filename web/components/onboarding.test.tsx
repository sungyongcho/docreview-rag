import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Onboarding } from "./onboarding";

describe("onboarding", () => {
  it("walks through five steps and closes on finish", () => {
    const close = vi.fn();
    render(<Onboarding onClose={close} />);

    expect(screen.getByText("Step 1 of 5")).toBeInTheDocument();
    for (let step = 0; step < 4; step += 1) fireEvent.click(screen.getByText("Next"));
    expect(screen.getByText("Step 5 of 5")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Finish"));

    expect(close).toHaveBeenCalledOnce();
  });
});
