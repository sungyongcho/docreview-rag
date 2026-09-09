import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { DatasetLock } from "./dataset-lock";

afterEach(cleanup);
it("renders read-only help in the page without a native title or button", () => {
  render(<DatasetLock />);
  const marker = screen.getByRole("img");
  expect(marker).not.toHaveAttribute("title");
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  fireEvent.mouseEnter(marker);
  expect(screen.getByRole("tooltip")).toHaveTextContent("Create a draft to edit");
  fireEvent.mouseLeave(marker);
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  fireEvent.focus(marker);
  expect(screen.getByRole("tooltip")).toBeVisible();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
});
