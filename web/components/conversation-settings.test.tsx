import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DEFAULT_PROFILE, DEFAULT_SESSION_PROFILE } from "@/lib/types";
import { ConversationSettings } from "./conversation-settings";

afterEach(cleanup);

it("edits only the current conversation policy and reads the next conversation's values", () => {
  const onChange = vi.fn();
  const props = { editable: true, onChange, onTabChange: vi.fn(), onClose: vi.fn() };
  const { rerender } = render(<ConversationSettings {...props} tab="limits" profile={DEFAULT_SESSION_PROFILE} />);
  fireEvent.change(screen.getByLabelText("Maximum wall clock seconds"), { target: { value: "240" } });
  expect(onChange).toHaveBeenCalledWith({ prompt_policy: { ...DEFAULT_SESSION_PROFILE.prompt_policy, workflow_budget: { ...DEFAULT_SESSION_PROFILE.prompt_policy.workflow_budget, max_wall_clock_s: 240 } } });
  rerender(<ConversationSettings {...props} tab="limits" profile={{ ...DEFAULT_SESSION_PROFILE, prompt_policy: { ...DEFAULT_SESSION_PROFILE.prompt_policy, workflow_budget: { ...DEFAULT_SESSION_PROFILE.prompt_policy.workflow_budget, max_wall_clock_s: 90 } } }} />);
  expect(screen.getByLabelText("Maximum wall clock seconds")).toHaveValue(90);
  fireEvent.keyDown(screen.getByRole("region", { name: "Conversation settings" }), { key: "Escape" });
  expect(props.onClose).toHaveBeenCalledOnce();
});

it("uses the conversation candidate and fusion limits for custom retrieval", () => {
  render(<ConversationSettings tab="retrieval" editable profile={{ ...DEFAULT_SESSION_PROFILE, retrieval_preset: "custom", custom_retrieval: DEFAULT_PROFILE }} onChange={vi.fn()} onTabChange={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByLabelText("candidate_k")).toHaveAttribute("max", "100");
  expect(screen.getByLabelText("candidate_k")).toHaveAttribute("min", String(DEFAULT_PROFILE.k));
  expect(screen.getByLabelText("RRF k")).toHaveAttribute("max", "10000");
});

it("keeps allowed filters but hides developer controls in public mode", () => {
  render(<ConversationSettings tab="limits" editable={false} profile={DEFAULT_SESSION_PROFILE} onChange={vi.fn()} onTabChange={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByLabelText("Companies")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Run limits" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Maximum wall clock seconds")).not.toBeInTheDocument();
});
