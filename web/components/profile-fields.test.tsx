import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProfileFields } from "./profile-fields";
import { DEFAULT_PROFILE } from "@/lib/types";
afterEach(cleanup);
it("groups parameters and shows compact help without changing values", () => {
  const change = vi.fn(); render(<ProfileFields profile={{ ...DEFAULT_PROFILE, lexical_ranker: "bm25" }} onChange={change} />);
  expect(screen.getByText("BM25 tuning").closest("details")).toHaveAttribute("open");
  const info = screen.getByRole("button", { name: "About BM25 k1" });
  fireEvent.mouseEnter(info);
  expect(screen.getByRole("tooltip")).toHaveTextContent("repeated terms");
  expect(change).not.toHaveBeenCalled();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).toBeNull();
  fireEvent.click(screen.getByText("BM25 tuning"));
  expect(screen.getByText("BM25 tuning").closest("details")).not.toHaveAttribute("open");
});
