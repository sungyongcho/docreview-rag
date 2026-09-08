import { describe, expect, it } from "vitest";
import { navigationLabel, navigationUrl, parseNavigationUrl, type NavigationTarget } from "./navigation";

describe("workspace navigation URLs", () => {
  it.each<NavigationTarget>([
    { view: "review", conversationId: "saved / conversation" },
    { view: "build", tab: "pipeline", stage: 7 },
    { view: "build", tab: "pipeline", stage: "setup" },
    { view: "build", tab: "documents" },
    { view: "build", tab: "jobs" },
    { view: "build", tab: "jobs", jobId: "admin-notification-1" },
    ...["playground", "golden", "runs", "compare", "snapshots", "presets"].map((tab) => ({ view: "measure" as const, tab: tab as "runs", resultId: 42 })),
    ...["status", "operations", "api", "usage"].map((tab) => ({ view: "system" as const, tab: tab as "status" })),
  ])("round-trips the complete destination %j", (target) => {
    const url = navigationUrl(target, "/docreview-rag-agent/?locale=ko&theme=light&help=review.scope#inspection");
    expect(url).toContain("/docreview-rag-agent/");
    expect(url).toContain("locale=ko"); expect(url).toContain("theme=light"); expect(url).toContain("help=review.scope"); expect(url).toContain("#inspection");
    expect(parseNavigationUrl(url, ["saved / conversation"], "fallback")).toEqual(target);
  });
  it("leaves legacy deep links to their existing route handler", () => {
    expect(parseNavigationUrl("/docreview-rag-agent/?help=review.scope", [], "fallback")).toBeNull();
  });
  it("replaces stale navigation parameters without dropping unrelated parameters", () => {
    const url = navigationUrl({ view: "review", conversationId: "next" }, "/docreview-rag-agent/?view=build&tab=pipeline&stage=2&result=7&conversation=old&locale=en#keep");
    expect(url).toBe("/docreview-rag-agent/?locale=en&view=review&conversation=next#keep");
  });
  it("falls back for unknown local conversations and invalid views", () => {
    expect(parseNavigationUrl("?view=review&conversation=missing", ["last"], "last")).toEqual({ view: "review", conversationId: "last" });
    expect(parseNavigationUrl("?view=alien", ["last"], "last")).toEqual({ view: "review", conversationId: "last" });
  });
  it.each(["-1", "0", "1.2", "1e2", "8", "9007199254740992", "nope"])("rejects invalid pipeline stage %s", (stage) => {
    expect(parseNavigationUrl(`?view=build&stage=${stage}&tab=invalid`, [], "last")).toEqual({ view: "build", tab: "pipeline" });
  });
  it("rejects incompatible stages and invalid tabs or result IDs", () => {
    expect(parseNavigationUrl("?view=build&tab=documents&stage=2", [], "last")).toEqual({ view: "build", tab: "documents" });
    expect(parseNavigationUrl("?view=measure&tab=__proto__&result=1.5", [], "last")).toEqual({ view: "measure", tab: "playground" });
    expect(parseNavigationUrl("?view=system&tab=constructor", [], "last")).toEqual({ view: "system", tab: "status" });
  });
  it("names tabs, pipeline steps, result IDs and saved conversation titles", () => {
    const t = (key: string) => key;
    expect(navigationLabel({ view: "review", conversationId: "a" }, { a: "NVIDIA filings" }, t)).toBe("Conversation · NVIDIA filings");
    expect(navigationLabel({ view: "build", tab: "pipeline", stage: 2 }, {}, t)).toBe("Build · Pipeline · Step 2");
    expect(navigationLabel({ view: "measure", tab: "runs", resultId: 10 }, {}, t)).toBe("Measure · Run evaluation · Result details");
    expect(navigationLabel({ view: "system", tab: "usage" }, {}, t)).toBe("System · Usage");
  });
});
