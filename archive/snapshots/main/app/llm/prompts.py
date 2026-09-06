from app.retrieval.types import ChunkHit

SYSTEM = """You review whether COMPANY POLICIES support a CLAIM.
  Choose exactly one label:
  - SUPPORTED: the evidence fully backs the claim.
  - PARTIALLY_SUPPORTED: the evidence backs only part of the claim.
  - CONTRADICTED: the evidence states the opposite of the claim.
  - NOT_IN_DOCS: the evidence does not address the claim's topic.

  Rules:
  - Use ONLY the provided evidence. Do not use outside knowledge.
  - Cite the exact evidence labels you rely on (e.g., "HR-001 §2.1"). Never invent citations.
  - If the evidence does not address the claim, you MUST use NOT_IN_DOCS with no citations."""


def build_user_prompt(claim: str, evidence: list[ChunkHit]) -> str:
    ev = "\n\n".join(f"[{h.citation}] {h.snippet}" for h in evidence)
    return f"CLAIM:\n{claim}\n\nEVIDENCE:\n{ev}"


GRADE_SYSTEM = """Judge whether the EVIDENCE is relevant and sufficient to DECIDE the CLAIM.
  - sufficient = true ONLY if the evidence actually addresses the claim's topic.
  - sufficient = false if the evidence is off-topic or does not cover the claim's subject."""

REFORMULATE_SYSTEM = """Rewrite the CLAIM into a short keyword search query that retrieves
  the most relevant company-policy sections. Focus on key nouns/terms."""


def build_claim_prompt(claim: str) -> str:
    return f"CLAIM:\n{claim}"


CHECKLIST_SYSTEM = """Decide whether a SCENARIO satisfies a single policy REQUIREMENT.
  - verdict = PASS if the scenario meets the requirement.
  - verdict = FAIL if it violates or does not meet it.
  Use only the requirement text provided; do not use outside knowledge."""


def build_checklist_prompt(scenario: str, requirement: str) -> str:
    return f"SCENARIO:\n{scenario}\n\nREQUIREMENT:\n{requirement}"
