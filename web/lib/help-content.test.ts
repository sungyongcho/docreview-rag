import { afterEach, describe, expect, it, vi } from "vitest";

import { accessibleHelpTopic, HELP_TOPICS, helpScreen, type HelpScreen } from "./help-content";
import type { Capabilities } from "./types";

const SCREENS = Object.keys(HELP_TOPICS) as HelpScreen[];
const ALL_TOPICS = SCREENS.flatMap((screen) => HELP_TOPICS[screen]);

describe("help content", () => {

  it("keeps topic ids unique across all screens", () => {
    const ids = ALL_TOPICS.map((topic) => topic.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("points every See also link at an existing topic other than itself", () => {
    for (const topic of ALL_TOPICS) {
      for (const ref of topic.seeAlso ?? []) {
        expect(ALL_TOPICS.some((candidate) => candidate.id === ref), `${topic.id} → ${ref}`).toBe(true);
        expect(ref, topic.id).not.toBe(topic.id);
      }
    }
  });

  it("maps the shell's view and tab to a screen", () => {
    expect(helpScreen("review", "")).toBe("review");
    expect(helpScreen("review", "anything")).toBe("review");
    expect(helpScreen("system", "status")).toBe("system");
    expect(helpScreen("system", "usage")).toBe("system");
    expect(helpScreen("build", "pipeline")).toBe("build");
    expect(helpScreen("build", "documents")).toBe("build.documents");
    expect(helpScreen("build", "jobs")).toBe("build.jobs");
    for (const tab of ["playground", "golden", "runs", "compare", "snapshots"]) expect(helpScreen("measure", tab)).toBe(`measure.${tab}`);
    expect(helpScreen("measure", "other")).toBeNull();
  });

  it("requires the evaluation workspace before offering snapshot creation or editing instructions", () => {
    const capabilities: Capabilities = { environment: "dev", can_configure_local_llm: true, can_edit_prompt_policy: true, can_edit_run_limits: true, can_edit_golden: true, can_build_snapshot: true, can_run_evaluation: false, can_change_custom_retrieval: true, can_query_snapshot: true, can_use_operations: true, can_compare_published_snapshots: true };
    const freeze = ALL_TOPICS.find((topic) => topic.id === "measure.snapshots.freeze")!;
    const snapshots = ALL_TOPICS.find((topic) => topic.id === "measure.snapshots.list")!;
    expect(accessibleHelpTopic(freeze, { capabilities })).toBeNull();
    const publicSnapshots = accessibleHelpTopic(snapshots, { capabilities });
    expect(publicSnapshots?.body.join(" ")).toContain("Browse published snapshots");
    expect(publicSnapshots?.body.join(" ")).not.toMatch(/Use for review|Publish or Hide/);
    expect(publicSnapshots?.guide).toEqual(snapshots.publicContent?.guide);

    const evaluationAccess = { capabilities: { ...capabilities, can_run_evaluation: true } };
    expect(accessibleHelpTopic(freeze, evaluationAccess)).toBe(freeze);
    expect(accessibleHelpTopic(snapshots, evaluationAccess)).toBe(snapshots);
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

    expect(operatorTopic?.body.join(" ")).toContain("Settings › Local LLM");
    const local = Object.values(operator.HELP_TOPICS).flat().find((topic) => topic.id === "system.local-policy")!;
    expect(operator.accessibleHelpTopic(local, { capabilities: { environment: "prod", can_configure_local_llm: true } as import("./types").Capabilities })).toBeNull();
    expect(operator.accessibleHelpTopic(local, { capabilities: { environment: "dev", can_configure_local_llm: true } as import("./types").Capabilities })).not.toBeNull();
  });
});
