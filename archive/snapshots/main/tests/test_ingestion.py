from app.config import get_settings
from app.ingestion.markdown_parser import parse_corpus, parse_document

SEED = get_settings().seed_dir
EXPECTED_DOC_IDS = {"DR-001", "HR-001", "EXP-001", "ONB-001", "SEC-001", "VND-001"}


def test_parse_corpus_covers_all_docs():
    sections = parse_corpus(SEED)
    assert {s.doc_id for s in sections} == EXPECTED_DOC_IDS
    assert len(sections) > 20  # 문서당 여러 섹션


def test_citation_format_is_stable():
    # 모든 섹션의 인용이 "DOC §SECTION" 형식이어야 채점 때 골든과 직접 비교 가능
    for s in parse_corpus(SEED):
        assert s.citation == f"{s.doc_id} §{s.section}"


def test_known_golden_section_present():
    # 골든 RQ-001의 정답 근거: HR-001 §2.1 (PTO). 파서가 이 인용을 만들어내야 함
    cites = {s.citation for s in parse_corpus(SEED)}
    assert "HR-001 §2.1" in cites


def test_parse_document_single_doc_id():
    sections = parse_document(SEED / "employee-handbook.md")
    assert sections
    assert all(s.doc_id == "HR-001" for s in sections)
    assert all(s.content is not None for s in sections)
