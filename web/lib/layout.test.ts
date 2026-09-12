import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("review shell layout", () => {
  it("keeps shell chrome fixed while only messages scroll", () => {
    const css = readFileSync("app/styles.css", "utf8");

    expect(css).toMatch(/\.service-shell\s*\{[^}]*height:\s*100dvh/);
    expect(css).toMatch(/\.sidebar\s*\{[^}]*height:\s*100dvh/);
    expect(css).toMatch(/\.workspace\s*\{[^}]*height:\s*100dvh/);
    expect(css).toMatch(/\.review-workspace\s*\{[^}]*min-height:\s*0[^}]*overflow:\s*hidden/);
    expect(css).toMatch(/\.messages\s*\{[^}]*width:\s*100%[^}]*height:\s*100%/);
    expect(css).toMatch(/\.messages-inner\s*\{[^}]*width:\s*min\(820px,\s*calc\(100% - 32px\)\)/);
    expect(css).toContain("overflow-y: auto;");
    expect(css).toMatch(/\.composer-wrap\s*\{[^}]*position:\s*relative[^}]*z-index:\s*2[^}]*width:\s*100%/);
  });
});
