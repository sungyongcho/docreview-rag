import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { Bm25Explorer } from "./bm25-explorer";

afterEach(cleanup);

it.each(["ko", "en"] as const)("changes illustrative scores without claiming evidence acceptance in %s", (locale) => {
  const { container } = render(<Bm25Explorer locale={locale} />);
  const score = () => container.querySelector(".bm25-demo-score strong")?.textContent;
  const initial = score();
  expect(screen.getByText(locale === "ko" ? /근거 채택 여부는 점수만으로 정하지 않고/ : /Evidence support is established by later checks/)).toBeInTheDocument();
  fireEvent.change(screen.getByRole("slider", { name: /^k1/ }), { target: { value: "3" } });
  expect(score()).not.toBe(initial);
  fireEvent.change(screen.getByRole("slider", { name: /^k1/ }), { target: { value: "0.2" } });
  expect(container.querySelector(".bm25-score-mark, .bm25-demo-verdict")).toBeNull();
  expect(screen.queryByText(/이 문서는 근거로 채택됩니다|근거에서 빠집니다|this document is selected as evidence|drops out of the evidence/)).toBeNull();
});
