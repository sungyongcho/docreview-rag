import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PipelineNext } from "./pipeline-next";
import { RetainedPanel } from "./retained-panel";

afterEach(() => { cleanup(); vi.useRealTimers(); });

it("shows the countdown inside the button and advances after three seconds", () => {
  vi.useFakeTimers(); const next = vi.fn(); render(<PipelineNext onNext={next} />);
  fireEvent.click(screen.getByRole("button", { name: "Next step" }));
  expect(screen.getByRole("button", { name: /Continue/ })).toContainElement(screen.getByRole("status"));
  expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent("3");
  act(() => vi.advanceTimersByTime(2000)); expect(screen.getByRole("status")).toHaveTextContent("1");
  expect(next).not.toHaveBeenCalled(); act(() => vi.advanceTimersByTime(1000)); expect(next).toHaveBeenCalledTimes(1);
});

it("cancels navigation when its workspace is hidden", () => {
  vi.useFakeTimers(); const next = vi.fn();
  const view = render(<RetainedPanel active><PipelineNext onNext={next} /></RetainedPanel>);
  fireEvent.click(screen.getByRole("button", { name: "Next step" }));
  view.rerender(<RetainedPanel active={false}><PipelineNext onNext={next} /></RetainedPanel>);
  act(() => vi.advanceTimersByTime(3000)); expect(next).not.toHaveBeenCalled();
});

it("allows a second click to advance once and shows completed steps without a countdown", () => {
  vi.useFakeTimers(); const next = vi.fn(); const view = render(<PipelineNext onNext={next} />);
  fireEvent.click(screen.getByRole("button", { name: "Next step" }));
  fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
  act(() => vi.advanceTimersByTime(3000)); expect(next).toHaveBeenCalledTimes(1);
  view.unmount(); render(<PipelineNext completed onNext={next} />);
  expect(screen.getByRole("button", { name: "Complete" })).toHaveClass("pipeline-confirmed");
  expect(screen.queryByRole("status")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Complete" })); expect(next).toHaveBeenCalledTimes(2);
});
