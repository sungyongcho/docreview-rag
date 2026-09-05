import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useEffect, useState } from "react";
import { afterEach, expect, it, vi } from "vitest";

import { RetainedPanel, useRetainedPanelActive } from "./retained-panel";

afterEach(cleanup);

/** Stand in for a workspace editor whose first mount starts its initial request. */
function Editor({ onMount }: { onMount: () => void }) {
  const active = useRetainedPanelActive();
  const [draft, setDraft] = useState("");
  useEffect(onMount, [onMount]);
  return <input aria-label="Draft" data-active={active} value={draft} onChange={(event) => setDraft(event.target.value)} />;
}

it("mounts nested panels only on a visible visit and retains their editor without duplicate initialization", () => {
  const onMount = vi.fn();
  const content = (workspace: boolean, tab: boolean) => <RetainedPanel active={workspace}><RetainedPanel active={tab}><Editor onMount={onMount} /></RetainedPanel></RetainedPanel>;
  const { rerender } = render(content(true, false));
  expect(onMount).not.toHaveBeenCalled();
  rerender(content(false, true));
  expect(onMount).not.toHaveBeenCalled();
  rerender(content(true, true));
  const draft = screen.getByRole("textbox", { name: "Draft" });
  fireEvent.change(draft, { target: { value: "Unsaved filter input" } });
  expect(onMount).toHaveBeenCalledTimes(1);
  rerender(content(false, true));
  expect(draft).not.toBeVisible();
  expect(draft).toHaveAttribute("data-active", "false");
  rerender(content(true, true));
  expect(draft).toBeVisible();
  expect(draft).toHaveValue("Unsaved filter input");
  expect(onMount).toHaveBeenCalledTimes(1);
});
