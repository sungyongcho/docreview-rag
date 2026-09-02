import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Onboarding, TOUR_TARGETS } from "./onboarding";

/** A host that, like the shell, mounts a step's target only after the step asked for its workspace. */
function ViewGatedHost({ onClose }: { onClose: () => void }) {
  const [location, setLocation] = useState("");
  return (
    <>
      {location === "build/pipeline" && <ol data-tour="stage-list"><li>Stage list</li></ol>}
      <Onboarding onClose={onClose} onStepChange={(step) => setLocation(`${step.view}/${step.tab ?? ""}`)} location={location} />
    </>
  );
}

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
    render(<><button data-tour="build" type="button">Build target</button><Onboarding onClose={close} /></>);

    fireEvent.click(screen.getByText("Build target"));

    expect(screen.getByText("Step 2 of 7")).toBeInTheDocument();
    expect(screen.getByText("Seven steps, in order")).toBeInTheDocument();
  });

  it("tells the shell which workspace each step needs", () => {
    const stepChange = vi.fn();
    render(<Onboarding onClose={vi.fn()} onStepChange={stepChange} />);

    expect(stepChange).toHaveBeenCalledTimes(1);
    expect(stepChange).toHaveBeenLastCalledWith({ view: "build" });
    fireEvent.click(screen.getByText("Next"));
    expect(stepChange).toHaveBeenLastCalledWith({ view: "build", tab: "pipeline" });
    fireEvent.click(screen.getByText("Next"));
    fireEvent.click(screen.getByText("Next"));

    expect(screen.getByText("Step 4 of 7")).toBeInTheDocument();
    expect(stepChange).toHaveBeenLastCalledWith({ view: "review" });
  });

  it("re-measures a target that mounts only after the host navigates", () => {
    // A stable onClose: the spotlight must follow `location`, not a callback identity that happens to change.
    const close = vi.fn();
    render(<ViewGatedHost onClose={close} />);
    expect(document.querySelector(".tour-shade-full")).not.toBeNull();
    expect(document.querySelector(".tour-spotlight")).toBeNull();

    fireEvent.click(screen.getByText("Next"));

    expect(screen.getByText("Step 2 of 7")).toBeInTheDocument();
    expect(document.querySelector(".tour-spotlight")).not.toBeNull();
    expect(document.querySelector(".tour-shade-full")).toBeNull();
    fireEvent.click(screen.getByText("Stage list"));
    expect(screen.getByText("Step 3 of 7")).toBeInTheDocument();
    expect(close).not.toHaveBeenCalled();
  });

  it("includes the local Operations target only when available", () => {
    render(<Onboarding onClose={vi.fn()} includeOperations />);
    expect(screen.getByText("Step 1 of 8")).toBeInTheDocument();
  });

  it("lists every spotlight target once", () => {
    expect([...TOUR_TARGETS]).toEqual([
      "build", "stage-list", "next-step", "new-review", "composer", "evidence-toggle", "evidence-fallback", "measure", "operations",
    ]);
  });
});
