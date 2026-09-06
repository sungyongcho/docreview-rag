import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MarkdownMessage } from "./markdown-message";

describe("MarkdownMessage", () => {
  it("renders GFM tables and code without allowing HTML or remote images", () => {
    const markdown = [
      "| Metric | Value |",
      "|---|---:|",
      "| Revenue | **42** |",
      "",
      "`inline`",
      "",
      "<script>alert('x')</script>",
      "",
      "![tracker](https://example.com/pixel.png)",
    ].join("\n");

    const { container } = render(<MarkdownMessage>{markdown}</MarkdownMessage>);

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("42").tagName).toBe("STRONG");
    expect(screen.getByText("inline").tagName).toBe("CODE");
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("[Image omitted: tracker]")).toBeInTheDocument();
  });

  it("opens only safe external links in a protected new tab", () => {
    render(<MarkdownMessage>{"[safe](https://example.com) [bad](javascript:alert(1))"}</MarkdownMessage>);

    expect(screen.getByText("safe")).toHaveAttribute("target", "_blank");
    expect(screen.getByText("safe")).toHaveAttribute("rel", "noreferrer noopener");
    expect(screen.getByText("bad").tagName).toBe("SPAN");
  });
});
