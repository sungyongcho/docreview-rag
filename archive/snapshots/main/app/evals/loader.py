from dataclasses import dataclass
import json
from pathlib import Path


@dataclass
class RetrievalCase:
    id: str
    question: str
    expected_citations: list[str]  # ["HR-001 §2.1", ...]


def load_retrieval_golden(dataset_root: Path) -> list[RetrievalCase]:
    path = dataset_root / "golden" / "retrieval_questions.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for q in data["questions"]:
        doc_id = q["expected"]["doc_id"]
        cites = [f"{doc_id} §{s}" for s in q["expected"]["sections"]]
        cases.append(RetrievalCase(q["id"], q["question"], cites))
    return cases


@dataclass
class ClaimCase:
    id: str
    claim: str
    label: str


def load_claim_golden(dataset_root: Path) -> list[ClaimCase]:
    data = json.loads(
        (dataset_root / "golden" / "claim_support_cases.json").read_text(
            encoding="utf-8"
        )
    )
    return [ClaimCase(c["id"], c["claim"], c["label"]) for c in data["cases"]]


@dataclass
class ChecklistCase:
    id: str
    scenario: str
    items: list[dict]
    overall: str


def load_checklist_golden(dataset_root: Path) -> list[ChecklistCase]:
    data = json.loads(
        (dataset_root / "golden" / "review_checklist_cases.json").read_text(
            encoding="utf-8"
        )
    )
    return [
        ChecklistCase(c["id"], c["scenario"], c["items"], c["overall"])
        for c in data["cases"]
    ]
