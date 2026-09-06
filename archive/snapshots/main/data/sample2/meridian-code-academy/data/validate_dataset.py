#!/usr/bin/env python3
"""
Validate that every (doc_id, section) reference in the golden files actually
exists in the synthetic source documents. This is what makes synthetic data
trustworthy as ground truth: if a golden case cites HR-001 2.3, section 2.3
must exist in employee-handbook.md. Run after editing any doc or golden file.

Usage:  python data/validate_dataset.py
Exit code 0 = all references resolve; 1 = at least one dangling reference.
"""
import json
import re
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent
SEED = DATA / "seed" / "synthetic"
GOLDEN = DATA / "golden"

DOC_ID_RE = re.compile(r"doc_id:\s*([A-Z]+-[A-Z0-9]+)")
# Headings like "## 2. Title" or "### 2.3 Title" -> capture 2 and 2.3
HEADING_RE = re.compile(r"^#{1,6}\s+(\d+(?:\.\d+)*)\b", re.MULTILINE)


def load_docs():
    docs = {}
    for md in sorted(SEED.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        m = DOC_ID_RE.search(text)
        if not m:
            print(f"  WARN: no doc_id header in {md.name}")
            continue
        doc_id = m.group(1)
        sections = set(HEADING_RE.findall(text))
        docs[doc_id] = {"file": md.name, "sections": sections}
    return docs


def iter_refs(obj):
    """Yield (doc_id, section) for every reference object anywhere in the JSON."""
    if isinstance(obj, dict):
        if "doc_id" in obj and "sections" in obj and isinstance(obj["sections"], list):
            for s in obj["sections"]:
                yield obj["doc_id"], str(s)
        for v in obj.values():
            yield from iter_refs(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_refs(v)


def main():
    docs = load_docs()
    print(f"Loaded {len(docs)} documents:")
    for doc_id, d in sorted(docs.items()):
        print(f"  {doc_id:8} {d['file']:42} sections={len(d['sections'])}")

    errors = []
    total_refs = 0
    for jf in sorted(GOLDEN.glob("*.json")):
        data = json.loads(jf.read_text(encoding="utf-8"))
        for doc_id, section in iter_refs(data):
            total_refs += 1
            if doc_id not in docs:
                errors.append(f"{jf.name}: references unknown doc_id {doc_id}")
            elif section not in docs[doc_id]["sections"]:
                errors.append(f"{jf.name}: {doc_id} has no section {section}")

    print(f"\nChecked {total_refs} (doc_id, section) references across "
          f"{len(list(GOLDEN.glob('*.json')))} golden files.")

    # Label distribution sanity check for claim cases
    cs = GOLDEN / "claim_support_cases.json"
    if cs.exists():
        cases = json.loads(cs.read_text(encoding="utf-8"))["cases"]
        dist = {}
        for c in cases:
            dist[c["label"]] = dist.get(c["label"], 0) + 1
        print("Claim-support label distribution:", dist)

    if errors:
        print(f"\nFAILED with {len(errors)} dangling reference(s):")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    print("\nOK: every golden reference resolves to a real section.")


if __name__ == "__main__":
    main()
