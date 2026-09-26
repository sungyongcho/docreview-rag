import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Onboarding } from "./onboarding";

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

  it("advances after the highlighted real target is clicked", () => {
    const close = vi.fn();
    render(<><button data-tour="build" type="button">Build target</button><Onboarding onClose={close} /></>);

    fireEvent.click(screen.getByText("Build target"));

    expect(screen.getByText("Step 2 of 7")).toBeInTheDocument();
    expect(screen.getByText("Seven steps, in order")).toBeInTheDocument();
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
});
