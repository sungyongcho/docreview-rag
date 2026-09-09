import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useConfirmation } from "./use-confirmation";

afterEach(cleanup);
function Probe({ changed }: { changed: (value: boolean) => void }) {
  const { confirm, confirmationDialog } = useConfirmation();
  return <>{confirmationDialog}<button onClick={async () => changed(await confirm("Change saved settings?"))}>Open</button></>;
}
it("keeps consent pending, traps focus, and restores it after Escape", async () => {
  const changed = vi.fn(); render(<Probe changed={changed} />);
  screen.getByText("Open").focus(); fireEvent.click(screen.getByText("Open"));
  expect(changed).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
  expect(screen.getByRole("button", { name: "Continue" })).toHaveFocus();
  fireEvent.keyDown(window, { key: "Escape" });
  await waitFor(() => expect(changed).toHaveBeenCalledWith(false));
  expect(screen.getByText("Open")).toHaveFocus();
});
it("cancels an unresolved operation when its owner unmounts", async () => {
  const changed = vi.fn(); const view = render(<Probe changed={changed} />);
  fireEvent.click(screen.getByText("Open")); view.unmount();
  await waitFor(() => expect(changed).toHaveBeenCalledExactlyOnceWith(false));
});
