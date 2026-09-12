
<!-- ops:project:AUTO.md:v1 -->
# AUTO — unsupervised session continuation

AUTO is a mode layered on the session's existing role (WORKER or INTERACTIVE),
entered by an explicit user instruction such as "switch to auto mode". It covers the
case where the user steps away or sleeps mid-session: work continues without
conversation, and the user finds results and blockers already recorded on return.

## Authority

AUTO adds no authority. The session keeps exactly the grants its role already has;
separately gated operations — credential changes, deployments, destructive actions,
merges without standing authority — stay gated. When a gate is missing, the item
becomes a recorded blocker, not a workaround.

## Behavior

- Complete everything the role can self-judge: implement, verify, deliver, merge and
  deploy where standing authority exists.
- On a blocker, try reasonable alternatives first. When genuinely stuck, record it
  and move to the next item — never spin, poll idly or guess past a gate.
- Token discipline: batch related checks, prefer the narrowest meaningful
  verification, do not re-run passing suites or loop waiting on external state.

## Records — no new tracking files

- Keep the session issue's work-state marker current; post one comment per milestone
  or blocker, not per step. The dashboard renders these, so a returning user sees
  state at a glance without a chat transcript.
- A multi-track effort may keep one `plan.md` in the driving repository, updated in
  place: completed items marked, new blockers appended at the bottom.
- Never create `auto-plan.md` or other one-off tracking files; existing records
  (session issue, plan.md, DECISIONS.md) carry the state.

## Ending

When self-judgeable work is exhausted or everything remaining is blocked:

1. Post one AUTO summary comment on the session issue: what shipped, verification
   evidence and live state.
2. List each remaining blocker with what was tried, why it blocked and the exact
   user action that unblocks it (links where useful).
3. Update the work-state marker (`REVIEW_READY`, `BLOCKED` or the fitting state).
4. End the turn — no waiting loops, no half-finished silent state.
<!-- /ops:project:AUTO.md -->
