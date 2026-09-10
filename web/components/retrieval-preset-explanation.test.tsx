import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { RetrievalPresetExplanation } from "./retrieval-preset-explanation";
import { DEFAULT_SESSION_PROFILE } from "@/lib/types";
afterEach(cleanup);
it("names the changed Korean preset parameters and shows their baseline", () => {
 render(<RetrievalPresetExplanation profile={{ ...DEFAULT_SESSION_PROFILE, retrieval_preset: "korean" }} />);
 expect(screen.getByText("20 → 30")).toBeInTheDocument();
 expect(screen.getByText("ts_rank_cd → bm25")).toBeInTheDocument();
 expect(screen.getByText("Disabled → Enabled")).toBeInTheDocument();
 expect(screen.getByText("candidate_k")).toBeInTheDocument();
});
