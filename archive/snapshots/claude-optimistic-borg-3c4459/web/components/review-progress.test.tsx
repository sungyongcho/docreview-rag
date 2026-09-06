import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ReviewProgressSteps, currentStepIndex, progressCountsLabel, reviewProgressFromEvent } from "./review-progress";

afterEach(cleanup);

function stepClasses(): Array<string | null> {
  return screen.getAllByRole("listitem", { hidden: true }).map((item) => item.getAttribute("class"));
}

describe("ReviewProgressSteps", () => {
  it("marks the three steps before grade as done and grade as current", () => {
    render(<ReviewProgressSteps state={{ node: "grade", evidence: 20, relevant: 0, steps: 2 }} />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    expect(screen.getAllByRole("listitem", { hidden: true }).map((item) => item.textContent)).toEqual(["Classify", "Scope", "Retrieve", "Grade", "Check citations", "Report"]);
    expect(stepClasses()).toEqual(["done", "done", "done", "current", null, null]);
    expect(screen.getByText("Grade")).toHaveAttribute("aria-current", "step");
    expect(screen.getByText("Step 4 of 6: Grade")).toHaveClass("sr-only");
  });

  it("treats candidates as retrieve done and keeps real nodes while re-checking", () => {
    const { rerender } = render(<ReviewProgressSteps state={{ node: "candidates", evidence: 12, relevant: 0, steps: 0 }} />);
    expect(stepClasses()).toEqual(["done", "done", "done", "current", null, null]);
    rerender(<ReviewProgressSteps state={{ node: "grade", evidence: 4, relevant: 0, steps: 1, revalidating: true }} />);
    expect(screen.getByText("Re-checking selected evidence")).toBeInTheDocument();
    expect(stepClasses()).toEqual(["done", "done", "done", "current", null, null]);
    rerender(<ReviewProgressSteps state={{ node: "report", evidence: 4, relevant: 2, steps: 3, revalidating: true }} />);
    expect(stepClasses()).toEqual(["done", "done", "done", "done", "done", "current"]);
  });

  it("shows Replying… instead of the step list while chatting", () => {
    render(<ReviewProgressSteps state={{ node: "chat", evidence: 0, relevant: 0, steps: 1 }} />);
    expect(screen.getByText("Replying…")).toBeInTheDocument();
    expect(screen.queryByRole("list", { hidden: true })).toBeNull();
    expect(screen.getByText("0 candidates · 0 relevant · 1 model steps")).toBeInTheDocument();
  });

  it("always renders the three count segments", () => {
    expect(progressCountsLabel({ node: "retrieve", evidence: 0, relevant: 0, steps: 0 })).toBe("0 candidates · 0 relevant · 0 model steps");
    expect(progressCountsLabel({ node: "check", evidence: 20, relevant: 6, steps: 3 })).toBe("20 candidates · 6 relevant · 3 model steps");
    render(<ReviewProgressSteps state={{ node: "check", evidence: 20, relevant: 6, steps: 3 }} />);
    expect(screen.getByText("20 candidates · 6 relevant · 3 model steps")).toHaveClass("review-progress-counts");
  });

  it("maps stream events and node indexes", () => {
    expect(reviewProgressFromEvent({ node: "report", evidence_count: 8, relevant_count: 3, step_count: 5 })).toEqual({ node: "report", evidence: 8, relevant: 3, steps: 5 });
    expect(currentStepIndex("gate")).toBe(0);
    expect(currentStepIndex("report")).toBe(5);
  });
});
