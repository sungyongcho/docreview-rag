# M9 Bugs — Failures worth keeping

## B1 — Strict models rejected the model's own JSON

`AgentAnswer` inherits the strict frozen base, and strict validation refuses to coerce a JSON array into a tuple field. Every syntactically perfect `final_answer` payload was rejected as invalid, and the loop burned its budget retrying an answer that was never wrong. Fix: the loop validates provider JSON with `strict=False` — transport coercion is lax while `extra="forbid"` still rejects unknown keys. The lesson generalizes: strictness belongs to the contract, not to the wire format.

## B2 — A rejected citation still consumed the whole run

The first citation-gate implementation returned a terminal failure the moment a final answer cited an unretrieved chunk. That turns one model mistake into a dead run. The gate now sends the rejection back as an observation naming the offending chunk ids, so the model can search again or answer `NOT_IN_DOCS` within the same budget.

## B3 — Failing tools were invisible to the model

An early dispatch draft let tool exceptions propagate, killing the run and telling the model nothing. The model then "remembered" tool outputs that never happened in later turns of manual testing. Every failure class now becomes an explicit `ERROR:` observation — the model must never be left guessing about what happened.

## B4 — The demo script cited evidence it could not have

The first offline CLI script had the deterministic provider answer `SUPPORTED` with a plausible chunk id. The loop correctly rejected it — the scripted provider cannot know which chunk ids the live search returned. The demo now answers `NOT_IN_DOCS`, which is the honest statement an evidence-gated agent can make without real evidence in hand.
