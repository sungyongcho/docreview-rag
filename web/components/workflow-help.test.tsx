import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
  fireEvent.click(screen.getByRole("button", { name: "How to use this page" }));
  expect(screen.getByRole("dialog")).toHaveTextContent("Document inventory");
  expect(container.querySelector(".development-badge")).toBeNull();
});

it("uses the same effective capability and preview gates for page help", () => {
  const capabilities = { environment: "dev", can_run_evaluation: true, can_edit_golden: true } as Capabilities;
  const { rerender, container } = render(<WorkflowHelp screen="measure.runs" capabilities={capabilities} />);
  expect(screen.getByLabelText("How to use this page")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "How to use this page" }));
  expect(document.querySelector(".workflow-help-panel .development-badge")).toHaveAttribute("aria-label", "DEV only");
  rerender(<WorkflowHelp screen="measure.runs" capabilities={capabilities} publicPreview />);
  expect(container).toBeEmptyDOMElement();
});


it("closes on page changes, leaving the workspace, outside clicks, and Escape", () => {
  const capabilities = { environment: "dev", can_run_evaluation: true, can_edit_golden: true } as Capabilities;
  const { rerender } = render(<WorkflowHelp screen="measure.runs" capabilities={capabilities} />);
  fireEvent.click(screen.getByRole("button"));
  expect(screen.getByRole("dialog")).toHaveStyle({ position: "fixed" });
  rerender(<WorkflowHelp screen="measure.snapshots" capabilities={capabilities} />);
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button"));
  rerender(<WorkflowHelp screen="measure.snapshots" capabilities={capabilities} active={false} />);
  expect(screen.queryByRole("dialog")).toBeNull();
  rerender(<WorkflowHelp screen="measure.snapshots" capabilities={capabilities} active />);
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button"));
  fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button"));
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByRole("button")).toHaveFocus();
});
