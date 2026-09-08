import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";
import ts from "typescript";
import { KO } from "./messages-ko";
import { describe, expect, it } from "vitest";
import { NOTIFICATION_EVENTS, notificationErrorMessage, notificationErrorDetail } from "./notification-registry";

/** Inspect production calls so adding a toast requires an explicit migration-class decision. */
function notificationCalls() {
  const rows: Array<{ path: string; line: number; event: string | null }> = [];
  for (const directory of ["components", "lib"]) {
    for (const name of readdirSync(directory, { recursive: true }) as string[]) {
      if (!/\.(tsx?|mjs)$/.test(name) || /\.(test|spec)\./.test(name) || /generated/.test(name)) continue;
      const path = join(directory, name);const source = ts.createSourceFile(path, readFileSync(path, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
      function visit(node: ts.Node) {
        if (ts.isCallExpression(node) && (ts.isIdentifier(node.expression) && node.expression.text === "notify" || ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === "notify")) {
          const options = node.arguments[4] ?? node.arguments[1];
          const property = options && ts.isObjectLiteralExpression(options) ? options.properties.find((item) => ts.isPropertyAssignment(item) && item.name.getText(source).replaceAll('"', "") === "event") : null;
          const event = property && ts.isPropertyAssignment(property) && ts.isStringLiteral(property.initializer) ? property.initializer.text : null;
          rows.push({ path, line: source.getLineAndCharacterOfPosition(node.getStart()).line + 1, event });
        }
        ts.forEachChild(node, visit);
      }
      visit(source);
    }
  }
  return rows;
}

describe("notification classification registry", () => {
  it("rejects every missing or unknown production classification", () => {
    const calls = notificationCalls();
    expect(calls.length).toBeGreaterThan(70);
    expect(calls.filter(row => !row.event || !Object.hasOwn(NOTIFICATION_EVENTS, row.event))).toEqual([]);
    for (const spec of Object.values(NOTIFICATION_EVENTS)) expect(["persistent", "transient", "inline-replaced"]).toContain(spec.classification);
  });
});


it("keeps API text intact while separating its structured cause and recovery target", () => {
  const error = Object.assign(new Error("Client prefix: original"), { failure: { message: "Original API message.", detail: "ValueError: original\nsecond line", cause: "invalid_json", path: "data/corpus/manifest.json", corpus_job: { job_id: "admin-1" } } });
  expect(notificationErrorMessage(error)).toBe("Original API message.");
  expect(notificationErrorDetail(error)).toEqual({ text: "ValueError: original\nsecond line", cause: "invalid_json", path: "data/corpus/manifest.json", fix: { view: "build", tab: "jobs", jobId: "admin-1" } });
});

it("retains every structured validation detail field", () => {
  const issue = { location: ["body", "query"], message: "Field required", error_type: "missing" };
  expect(JSON.parse(notificationErrorDetail({ details: [issue] })!.text!)).toEqual(issue);
});


it("localizes every registered notification title", () => {
  expect(Object.values(NOTIFICATION_EVENTS).filter(event => !(event.title in KO)).map(event => event.title)).toEqual([]);
});
