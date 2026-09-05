import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CodeBlock } from "./code-block";

it("copies exact code without language labels or decorations", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  const code = "rag-dev up -d\n  # keep indentation\n";
  render(<CodeBlock code={code} language="bash" html="<pre><code>highlighted display</code></pre>" />);
  fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(code));
  expect(screen.getByRole("status")).toHaveTextContent("Copied");
});
