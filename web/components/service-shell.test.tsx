import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ONBOARDING_KEY } from "@/lib/storage";
import { ServiceShell, terminalAnswer } from "./service-shell";

describe("service shell", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem(ONBOARDING_KEY, "done");
    vi.stubGlobal("crypto", { randomUUID: () => "conversation-id" });
  });

  it("renders the review shell and opens documentation in a new window", async () => {
    render(<ServiceShell />);

    await waitFor(() =>
      expect(screen.getByPlaceholderText("Ask a question about the filing corpus")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Data & help" }));
    const documentation = screen.getByText("Documentation").closest("a");

    expect(screen.getByText("Review filings with verifiable evidence.")).toBeInTheDocument();
    expect(documentation).toHaveAttribute("target", "_blank");
    expect(documentation).toHaveAttribute("href", "/docreview-rag-agent/docs/");
  });

  it("shows invalidated provider authentication instead of an evidence fallback", () => {
    const answer = terminalAnswer({
      status: "error",
      report: null,
      failure: {
        code: "provider_failure",
        status: "provider_error",
        details: ["AuthenticationError: token_invalidated"],
      },
    });

    expect(answer).toBe(
      "OpenAI API authentication failed. Update the server-side API key and retry.",
    );
  });
});
