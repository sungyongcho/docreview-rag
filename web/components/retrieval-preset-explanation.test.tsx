import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { RetrievalPresetExplanation } from "./retrieval-preset-explanation";
import { DEFAULT_SESSION_PROFILE } from "@/lib/types";
afterEach(cleanup);
it("names the changed Korean preset parameters and shows their baseline", () => {
 render(<RetrievalPresetExplanation profile={{ ...DEFAULT_SESSION_PROFILE, retrieval_preset: "korean" }} />);
 for (const [key, value] of [["candidate_k", "20 → 30"], ["lexical_ranker", "ts_rank_cd → bm25"], ["route_by_language", "Disabled → Enabled"]]) {
   expect(screen.getByText(key).closest(".preset-parameter")?.querySelector(".preset-parameter-value")).toHaveTextContent(value);
 }
});
