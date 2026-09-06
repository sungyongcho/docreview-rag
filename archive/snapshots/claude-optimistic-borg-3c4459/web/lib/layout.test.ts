import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("review shell layout", () => {
  it("keeps shell chrome fixed while only messages scroll", () => {
    const css = readFileSync("app/styles.css", "utf8");

    expect(css).toContain(".service-shell { height: 100dvh;");
    expect(css).toContain(".sidebar { height: 100dvh;");
    expect(css).toContain(".workspace { height: 100dvh;");
    expect(css).toContain(".review-workspace { min-height: 0; overflow: hidden;");
    expect(css).toContain(".messages { width: 100%; height: 100%;");
    expect(css).toContain(".messages-inner { width: min(820px, calc(100% - 32px));");
    expect(css).toContain("overflow-y: auto;");
    expect(css).toContain(".composer-wrap { position: relative; z-index: 2; width: 100%;");
  });
});
