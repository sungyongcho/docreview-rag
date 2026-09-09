import { act, cleanup, render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProfileCompatibilityNotice } from "./profile-compatibility-notice";
const { notify, dismissNotice } = vi.hoisted(() => ({ notify: vi.fn(), dismissNotice: vi.fn() }));
vi.mock("./notifications", () => ({ useNotifications: () => ({ notify, dismissNotice }) }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
it("uses the persistent shared toast, stays dismissed and adds no inline banner", () => {
  const view = render(<ProfileCompatibilityNotice message="Incompatible limits" conversationId="a" />);
  expect(view.container).toBeEmptyDOMElement();
  expect(notify).toHaveBeenCalledWith("Incompatible limits", "warning", "profile-compatibility:a", 0, expect.objectContaining({ event: "profile-compatibility-warning" }));
  act(() => notify.mock.calls[0][4].onDismiss());
  view.rerender(<ProfileCompatibilityNotice message="Incompatible limits" conversationId="a" />);
  expect(notify).toHaveBeenCalledTimes(1);
  expect(dismissNotice).toHaveBeenCalledWith("profile-compatibility:a");
});
