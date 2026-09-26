import { fireEvent, render } from "@testing-library/react";
import { vi } from "vitest";

import { Onboarding } from "./onboarding";

const TOUR_TARGET_SELECTOR = /^\[data-tour="(.+)"\]$/;

/**
 * Every `data-tour` name the complete tour (Operations step included) spotlights, in step order
 * and without repeats.
 *
 * The names are read from the selectors the tour queries while it walks an empty page, so the
 * list follows the component's real behaviour instead of a copy of its step table. On an empty
 * page no target is found, which makes the tour query every alternative target of every step.
 */
export function tourTargets(): string[] {
  const querySelector = vi.spyOn(document, "querySelector");
  const tour = render(<Onboarding onClose={() => undefined} includeOperations />);
  try {
    while (tour.queryByText("Finish") === null) {
      fireEvent.click(tour.getByText("Next"));
    }
    const targets: string[] = [];
    for (const [selector] of querySelector.mock.calls) {
      const match = TOUR_TARGET_SELECTOR.exec(String(selector));
      if (match && !targets.includes(match[1])) targets.push(match[1]);
    }
    return targets;
  } finally {
    tour.unmount();
    querySelector.mockRestore();
  }
}
