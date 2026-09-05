import { describe, expect, it } from "vitest";
import { helpDestinationScreen, searchHelp } from "./help-search";

describe("local bilingual help search", () => {
  it.each(["en", "ko"] as const)("finds Korean and English terms in %s UI", (locale) => {
    expect(searchHelp("실행 한도", locale).map(({ topic }) => topic.id)).toContain("review.run-limits");
    expect(searchHelp("Corpus scope", locale)[0].topic.id).toBe("review.scope");
  });
  it("requires every term and ranks title matches first", () => {
    expect(searchHelp("BM25 k1", "ko")[0].topic.id).toContain("bm25_k1");
    expect(searchHelp("totally-unmatched-help-query", "en")).toEqual([]);
  });
  it("routes conditional help to the screen where it can be enabled", () => {
    expect(helpDestinationScreen("review.snapshot")).toBe("measure.snapshots");
    expect(helpDestinationScreen("measure.snapshots.freeze")).toBe("measure.runs");
    expect(helpDestinationScreen("build.documents.filters")).toBe("build.documents");
  });
});
