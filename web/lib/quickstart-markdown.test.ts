import { describe, expect, it } from "vitest";
import { splitQuickStart } from "./quickstart-markdown.mjs";

const source = "Introduction\n<!-- quickstart-cli -->\nCLI commands\n<!-- quickstart-web -->\nWeb controls\n<!-- quickstart-end -->\nNext steps";

describe("split quick start guides", () => {
  it("preserves each authored section while separating CLI and Web instructions", () => {
    expect(splitQuickStart(source)).toEqual({ common: "Introduction\n", cli: "\nCLI commands\n", web: "\nWeb controls\n", after: "\nNext steps" });
  });

  it("rejects missing, repeated or out-of-order section markers", () => {
    for (const marker of ["<!-- quickstart-cli -->", "<!-- quickstart-web -->", "<!-- quickstart-end -->"]) {
      expect(() => splitQuickStart(source.replace(marker, ""))).toThrow();
      expect(() => splitQuickStart(source.replace(marker, marker + marker))).toThrow();
    }
    expect(() => splitQuickStart("<!-- quickstart-web --><!-- quickstart-cli --><!-- quickstart-end -->")).toThrow();
  });
});
