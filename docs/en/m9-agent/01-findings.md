# M9 Findings — What the fixed workflow cannot do

## F1 — The workflow's route is chosen by code, not by the question

M4 runs retrieve → grade → check → report for every request. That is exactly right for a single review question, and exactly wrong for tasks that need a different route: comparing two fiscal years takes two filtered retrievals; a vague question needs a follow-up search after reading the first evidence. The fixed graph cannot re-plan mid-run.

## F2 — Multi-hop questions lose recall under a single query

The M3 golden set carries a `multi_hop` category by design. A question that joins two facts ("how did X change between 2023 and 2024") retrieves against one mixed query embedding and one mixed lexical query, so each underlying fact competes with the other for the top-k. The suite-level score hides this: the gap only appears when metrics are sliced per category, which is what `app/agent/eval.py` exists to show.

## F3 — Handing the model a route requires harder contracts, not softer ones

Letting the model choose tools multiplies the ways a run can go wrong: unknown tools, malformed arguments, fabricated observations, invented citations, unbounded spending. Every one of those failure classes already had an M4-era answer — typed failures, budget guards, citation intersection — and M9 reuses each of them at the loop boundary instead of inventing new ones.

## F4 — One tool schema must serve three consumers

The model reads a prompt manual, the API receives function specs, and MCP clients fetch input schemas. Written separately, the three drift, and drift here means the model calls tools that do not exist or MCP clients send arguments the tools reject. The registry generates all three from the same `Tool` declaration, so drift is structurally impossible.
