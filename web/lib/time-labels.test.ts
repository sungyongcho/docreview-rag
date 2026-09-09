import { describe, expect, it } from "vitest";
import { relativeTime } from "./time-labels";

describe("relativeTime", () => {
  const now = Date.parse("2026-09-09T12:00:00Z");
  it("rounds recent ages into seconds, minutes and hours", () => {
    expect(relativeTime("2026-09-09T11:59:40Z", "en", now)).toBe("Just now");
    expect(relativeTime("2026-09-09T11:57:00Z", "en", now)).toBe("3 min ago");
    expect(relativeTime("2026-09-09T09:00:00Z", "en", now)).toBe("3 h ago");
    expect(relativeTime("2026-09-09T11:57:00Z", "ko", now)).toBe("3분 전");
  });
  it("prints a dated label after a day and tolerates invalid input", () => {
    expect(relativeTime("2026-09-07T09:30:00Z", "en", now)).toMatch(/Sep 7/);
    expect(relativeTime("not-a-date", "en", now)).toBe("");
  });
});
