import { expect, it } from "vitest";
import { HELP_TOPICS } from "./help-content";
import { HELP_GROUPS, getHelpPrimer } from "./help-primer";
import { KO } from "./messages-ko";
import { documentationDocument } from "./documentation-registry.mjs";

it("keeps every existing control reachable exactly once through four compact task groups", () => {
  const expected = Object.values(HELP_TOPICS).flat().map((topic) => topic.id).sort();
  const actual = HELP_GROUPS.flatMap((group) => group.clusters.flatMap((cluster) => cluster.topicIds));
  expect(HELP_GROUPS).toHaveLength(4);
  expect(new Set(actual).size).toBe(actual.length);
  expect([...actual].sort()).toEqual(expected);
  for (const group of HELP_GROUPS) expect(group.clusters.length).toBeLessThanOrEqual(4);
});

it("translates the navigation labels and concise guides used by dynamic Help views", () => {
  const labels = HELP_GROUPS.flatMap((group) => [group.title, group.summary, ...group.clusters.flatMap((cluster) => [cluster.title, cluster.summary])]);
  for (const topic of Object.values(HELP_TOPICS).flat()) {
    const primer = getHelpPrimer(topic);
    expect(primer.steps).toHaveLength(3);
    expect(documentationDocument(primer.documentId!, "en")).toBeDefined();
    expect(documentationDocument(primer.documentId!, "ko")).toBeDefined();
    labels.push(primer.summary, ...primer.steps);
  }
  expect([...new Set(labels)].filter((label) => !KO[label])).toEqual([]);
});
