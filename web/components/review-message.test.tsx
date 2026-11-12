import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { I18nProvider } from "@/lib/i18n";
import type { ChatMessage, EvidenceHold } from "@/lib/types";
import { ReviewMessage } from "./review-message";

afterEach(() => { cleanup(); localStorage.clear(); });

const HOLD: EvidenceHold = { registry: "sec", issuer: "AMD", fiscal_year: 2025, reason: "amendment_pending", items: [] };

/** Render one message with the callbacks the review shell supplies. */
function renderMessage(message: ChatMessage) {
  return render(
    <I18nProvider>
      <ReviewMessage message={message} latestEvidence={false} busy={false} onMark={() => undefined} onUseSelected={() => undefined} />
    </I18nProvider>,
  );
}

describe("ReviewMessage evidence holds", () => {
  it("names the held report period with the answer, even when no candidate is listed", () => {
    localStorage.setItem("docreview.locale", "en");
    renderMessage({ id: "a1", role: "assistant", text: "No evidence.", evidence: [], evidenceHolds: [HOLD] });

    expect(screen.getByText("No evidence.")).toBeInTheDocument();
    const notice = screen.getByRole("note", { name: "Evidence on hold" });
    expect(notice).toHaveTextContent("SEC · AMD · FY 2025");
    expect(notice).toHaveTextContent(/An amendment to this report has not been reviewed yet/);
  });

  it("shows no notice for an answer without holds or for the user's own message", () => {
    const { rerender } = renderMessage({ id: "a1", role: "assistant", text: "Revenue grew." });
    expect(screen.queryByRole("note")).toBeNull();

    rerender(
      <I18nProvider>
        <ReviewMessage message={{ id: "u1", role: "user", text: "Revenue?", evidenceHolds: [HOLD] }} latestEvidence={false} busy={false} onMark={() => undefined} onUseSelected={() => undefined} />
      </I18nProvider>,
    );
    expect(screen.queryByRole("note")).toBeNull();
  });
});
