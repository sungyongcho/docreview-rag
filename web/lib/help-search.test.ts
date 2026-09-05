import { describe, expect, it } from "vitest";
import { helpDestinationScreen, helpEntriesForAccess, searchHelp } from "./help-search";
import { developmentHelpTopic } from "./help-content";
import { getHelpPrimer } from "./help-primer";
import type { Capabilities } from "./types";

const DEV: Capabilities = { environment: "dev", can_configure_local_llm: true, can_edit_prompt_policy: true, can_edit_run_limits: true, can_edit_golden: true, can_build_snapshot: true, can_run_evaluation: true, can_change_custom_retrieval: true, can_query_snapshot: true, can_use_operations: true, can_compare_published_snapshots: true };

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

  it.each([{}, { publicPreview: true, capabilities: DEV }])("keeps public documents while excluding restricted topics in public or preview help", (access) => {
    const entries = helpEntriesForAccess(access);
    const ids = entries.map(({ topic }) => topic.id);
    for (const id of ["build.documents.filters", "build.documents.list", "build.documents.detail", "measure.snapshots.list", "review.preset", "review.rag"]) expect(ids).toContain(id);
    for (const id of ["build.stage.filings", "build.jobs.center", "review.retrieval", "review.run-limits", "measure.runs.queue", "measure.golden.revision", "measure.snapshots.freeze", "system.operations", "system.api"]) expect(ids).not.toContain(id);
    expect(entries.some(({ topic }) => developmentHelpTopic(topic))).toBe(false);
    for (const locale of ["en", "ko"] as const) expect(searchHelp("실행 한도", locale, entries).some(({ topic }) => topic.id === "review.run-limits")).toBe(false);
    const preset = entries.find(({ topic }) => topic.id === "review.preset")!.topic;
    expect([...preset.body, ...getHelpPrimer(preset).steps].join(" ")).not.toContain("Custom");
    const snapshots = entries.find(({ topic }) => topic.id === "measure.snapshots.list")!.topic;
    expect(snapshots.body.join(" ")).not.toContain("Publish or Hide");
  });

  it("honors individual editor and workspace capabilities instead of treating DEV as blanket permission", () => {
    const entries = helpEntriesForAccess({ capabilities: { ...DEV, can_edit_prompt_policy: false, can_run_evaluation: false } });
    const ids = entries.map(({ topic }) => topic.id);
    for (const id of ["review.retrieval", "review.retrieval.k", "review.run-limits", "measure.runs.queue", "measure.golden.revision"]) expect(ids).not.toContain(id);
    expect(ids).toContain("build.documents.list");
    expect(helpEntriesForAccess({ capabilities: DEV }).find(({ topic }) => topic.id === "review.retrieval")).toBeDefined();
  });
});
