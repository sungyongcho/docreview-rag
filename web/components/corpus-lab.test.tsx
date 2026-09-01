import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DEFAULT_PROFILE } from "@/lib/types";
import { CorpusLab } from "./corpus-lab";

describe("Corpus Lab", () => {
  it("keeps real corpus operations disabled in the public read-only mode", () => {
    render(
      <CorpusLab
        live={false}
        profile={DEFAULT_PROFILE}
        onProfileChange={vi.fn()}
        onApplyProfile={vi.fn()}
      />,
    );

    expect(screen.getByText("Read-only portfolio")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Acquire missing filings" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Ingest manifest" })).toBeDisabled();
  });
});
