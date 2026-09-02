import { afterEach, describe, expect, it, vi } from "vitest";

import { findHelpTopic, HELP_SCREEN_TITLES, HELP_TOPICS, helpScreen, type HelpScreen } from "./help-content";

const SCREENS = Object.keys(HELP_TOPICS) as HelpScreen[];
const ALL_TOPICS = SCREENS.flatMap((screen) => HELP_TOPICS[screen]);

describe("help content", () => {
  it("gives every screen at least one topic and a title", () => {
    for (const screen of SCREENS) {
      expect(HELP_TOPICS[screen].length, screen).toBeGreaterThan(0);
      expect(HELP_SCREEN_TITLES[screen]).toBeTruthy();
    }
  });

  it("keeps topic ids unique across all screens", () => {
    const ids = ALL_TOPICS.map((topic) => topic.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("prefixes every topic id with its screen", () => {
    for (const screen of SCREENS) {
      for (const topic of HELP_TOPICS[screen]) expect(topic.id.startsWith(`${screen}.`), topic.id).toBe(true);
    }
  });

  it("writes 1–4 plain sentences per topic with a title", () => {
    for (const topic of ALL_TOPICS) {
      expect(topic.title.trim(), topic.id).not.toBe("");
      expect(topic.body.length, topic.id).toBeGreaterThanOrEqual(1);
      expect(topic.body.length, topic.id).toBeLessThanOrEqual(4);
      for (const paragraph of topic.body) expect(paragraph.trim().length, topic.id).toBeGreaterThan(20);
    }
  });

  it("points every See also link at an existing topic other than itself", () => {
    for (const topic of ALL_TOPICS) {
      for (const ref of topic.seeAlso ?? []) {
        expect(findHelpTopic(ref), `${topic.id} → ${ref}`).not.toBeNull();
        expect(ref, topic.id).not.toBe(topic.id);
      }
    }
  });

  it("covers the existing Build hooks and the Playground profile fields", () => {
    const ids = new Set(HELP_TOPICS.build.map((topic) => topic.id));
    for (const stage of ["filings", "index", "embeddings", "lexical", "ask", "answer_model", "evaluate"]) expect(ids.has(`build.stage.${stage}`)).toBe(true);
    expect(ids.has("build.next-step")).toBe(true);
    const fields = ["strategy", "lexical_ranker", "k", "candidate_k", "rrf_k", "bm25_k1", "bm25_b", "bm25_idf", "reranker", "route_by_language"];
    const playground = new Set(HELP_TOPICS["measure.playground"].map((topic) => topic.id));
    const runs = HELP_TOPICS["measure.runs"];
    for (const field of fields) {
      expect(playground.has(`measure.playground.${field}`), field).toBe(true);
      expect(runs.find((topic) => topic.id === `measure.runs.${field}`)?.optional, field).toBe(true);
    }
  });

  it("maps the shell's view and tab to a screen", () => {
    expect(helpScreen("review", "")).toBe("review");
    expect(helpScreen("review", "anything")).toBe("review");
    expect(helpScreen("system", "status")).toBe("system");
    expect(helpScreen("system", "usage")).toBe("system");
    expect(helpScreen("build", "pipeline")).toBe("build");
    expect(helpScreen("build", "documents")).toBeNull();
    expect(helpScreen("build", "jobs")).toBe("build.jobs");
    for (const tab of ["playground", "golden", "runs", "compare", "snapshots"]) expect(helpScreen("measure", tab)).toBe(`measure.${tab}`);
    expect(helpScreen("measure", "other")).toBeNull();
  });
});

describe("build flavour", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("keeps the local engine out of a bundle that cannot run one", async () => {
    const publicTopic = HELP_TOPICS.build.find((topic) => topic.id === "build.stage.answer_model");
    expect(publicTopic?.body.join(" ")).not.toContain("LOCAL_LLM");

    vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
    vi.resetModules();
    const operator = await import("./help-content");
    const operatorTopic = operator.HELP_TOPICS.build.find(
      (topic) => topic.id === "build.stage.answer_model",
    );

    expect(operatorTopic?.body.join(" ")).toContain("LOCAL_LLM_BASE_URL");
  });
});
