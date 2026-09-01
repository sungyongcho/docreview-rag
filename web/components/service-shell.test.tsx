import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ONBOARDING_KEY } from "@/lib/storage";
import { ServiceShell } from "./service-shell";

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
    const documentation = screen.getByText("Documentation").closest("a");

    expect(screen.getByText("Review filings with verifiable evidence.")).toBeInTheDocument();
    expect(documentation).toHaveAttribute("target", "_blank");
    expect(documentation).toHaveAttribute("href", "/docreview-rag-agent/docs/");
  });
});
