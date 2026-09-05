import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { WorkflowHelp } from "./workflow-help";
import type { Capabilities } from "@/lib/types";

afterEach(cleanup);

it("does not bypass public restrictions through the page-level help disclosure", () => {
  const { rerender, container } = render(<WorkflowHelp screen="measure.runs" />);
  expect(container).toBeEmptyDOMElement();
  rerender(<WorkflowHelp screen="measure.snapshots" />);
  expect(container).not.toHaveTextContent("Publish or Hide");
  expect(container).not.toHaveTextContent("Save result as snapshot");
  expect(container.querySelector(".development-badge")).toBeNull();
  rerender(<WorkflowHelp screen="build.documents" />);
  expect(container).toHaveTextContent("Document inventory");
  expect(container.querySelector(".development-badge")).toBeNull();
});

it("uses the same effective capability and preview gates for page help", () => {
  const capabilities = { environment: "dev", can_run_evaluation: true, can_edit_golden: true } as Capabilities;
  const { rerender, container } = render(<WorkflowHelp screen="measure.runs" capabilities={capabilities} />);
  expect(screen.getByLabelText("How to use this page")).toBeInTheDocument();
  expect(container.querySelector(".development-badge")).toHaveAttribute("aria-label", "DEV only");
  rerender(<WorkflowHelp screen="measure.runs" capabilities={capabilities} publicPreview />);
  expect(container).toBeEmptyDOMElement();
});
