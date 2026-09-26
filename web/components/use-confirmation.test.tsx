import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useConfirmation } from "./use-confirmation";

afterEach(cleanup);
function Probe({ changed, onKeyDown }: { changed: (value: boolean) => void; onKeyDown?: () => void }) {
  const { confirm, confirmationDialog } = useConfirmation();
  return <div onKeyDown={onKeyDown}>{confirmationDialog}<button onClick={async () => changed(await confirm("Change saved settings?"))}>Open</button></div>;
}
it("keeps consent pending, traps focus, and restores it after Escape", async () => {
  const changed = vi.fn(); const parentKey = vi.fn();
  render(<Probe changed={changed} onKeyDown={parentKey} />);
  screen.getByText("Open").focus(); fireEvent.click(screen.getByText("Open"));
  expect(changed).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: "Tab", shiftKey: true });
  expect(screen.getByRole("button", { name: "Continue" })).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  await waitFor(() => expect(changed).toHaveBeenCalledWith(false));
  expect(screen.getByText("Open")).toHaveFocus();
  expect(parentKey).not.toHaveBeenCalled();
});
it("cancels an unresolved operation when its owner unmounts", async () => {
  const changed = vi.fn(); const view = render(<Probe changed={changed} />);
  fireEvent.click(screen.getByText("Open")); view.unmount();
  await waitFor(() => expect(changed).toHaveBeenCalledExactlyOnceWith(false));
});
