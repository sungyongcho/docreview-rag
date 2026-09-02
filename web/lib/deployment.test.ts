import { describe, expect, it } from "vitest";

import { deploymentLabel } from "./deployment";

describe("deploymentLabel", () => {
  it("derives a text-only deployment label from the current host", () => {
    expect(deploymentLabel("localhost")).toBe("DEV");
    expect(deploymentLabel("127.0.0.1")).toBe("DEV");
    expect(deploymentLabel("[::1]")).toBe("DEV");
    expect(deploymentLabel("app.localhost")).toBe("DEV");
    expect(deploymentLabel("review.example.com")).toBe("PROD");
  });
});
