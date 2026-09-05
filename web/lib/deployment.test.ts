import { describe, expect, it } from "vitest";
import { deploymentLabel } from "./deployment";

describe("deploymentLabel", () => {
  it("uses the server mode rather than the hostname and keeps unknown mode explicit", () => {
    expect(deploymentLabel("dev")).toBe("DEV");
    expect(deploymentLabel("prod")).toBe("PROD");
    expect(deploymentLabel()).toBe("Checking mode…");
  });
});
