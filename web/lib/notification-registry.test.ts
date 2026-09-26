import { KO } from "./messages-ko";
import { expect, it } from "vitest";
import { NOTIFICATION_EVENTS, notificationErrorMessage, notificationErrorDetail } from "./notification-registry";



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
