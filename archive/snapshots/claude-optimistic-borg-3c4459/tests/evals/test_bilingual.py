"""Korean golden-suite parity with immutable English source spans."""

import pytest

from app.evals.bilingual import (
    KO_GOLDEN_PATH,
    TWIN_INVARIANT_FIELDS,
    BilingualSuite,
    TwinCaseError,
    load_bilingual_suites,
    validate_twin_cases,
)
from app.evals.types import GoldenCase, GoldenSpan
from tests.evals.golden import ABSENT_CASE_COUNT, CASE_COUNT, CATEGORY_COUNTS, POSITIVE_CASE_COUNT
from tests.evals.support import SOURCE_SHA256

KO_PATH = KO_GOLDEN_PATH


def english_case(case_id: str = "m3c-01", **changes) -> GoldenCase:
    """Build one valid English positive case with optional field replacements."""
    values = {
        "id": case_id,
        "question": "How did AMD's gross margin change in fiscal 2019?",
        "category": "multi_hop",
        "facet": "comparison",
        "tags": ("margin",),
        "answers": (
            GoldenSpan(
                doc_id="AMD-FY2019",
                source_sha256=SOURCE_SHA256,
                start_char=100,
                end_char=200,
            ),
        ),
        "expected_label": "SUPPORTED",
        "reference_answer": "Gross margin rose from 38% to 43%.",
        "note": "Twin-validator fixture.",
        "curation_status": "agent-curated",
        "approval_status": "pending-author-approval",
        "human_verified": False,
    }
    values.update(changes)
    return GoldenCase(**values)


def korean_case(case_id: str = "m3c-01", **changes) -> GoldenCase:
    """Build the Korean twin of ``english_case`` with optional replacements."""
    return english_case(
        case_id,
        **{
            "question": "AMD의 매출총이익률은 2019 회계연도에 어떻게 변화했습니까?",
            **changes,
        },
    )


def test_the_korean_suite_ships_beside_the_frozen_english_one():
    """Ship the Korean golden suite at its declared default path."""
    assert KO_GOLDEN_PATH == KO_PATH
    assert KO_PATH.is_file()


def test_load_bilingual_suites_binds_both_languages_to_the_same_spans():
    """Bind both languages to the same ordered cases and source spans."""
    suite = load_bilingual_suites()

    assert len(suite.en) == CASE_COUNT
    assert len(suite.ko) == CASE_COUNT
    assert [case.id for case in suite.en] == sorted(case.id for case in suite.en)
    assert [case.id for case in suite.ko] == [case.id for case in suite.en]

    pairs = suite.pairs()
    assert len(pairs) == CASE_COUNT
    assert all(english.id == korean.id for english, korean in pairs)
    # The whole point of the twin design: one immutable set of answer coordinates.
    assert all(english.answers == korean.answers for english, korean in pairs)

    counts: dict[str, int] = {}
    for case in suite.ko:
        counts[case.category] = counts.get(case.category, 0) + 1
    assert counts == CATEGORY_COUNTS

    positives = [case for case in suite.ko if case.answers]
    absents = [case for case in suite.ko if not case.answers]
    assert len(positives) == POSITIVE_CASE_COUNT
    assert len(absents) == ABSENT_CASE_COUNT
    assert all(case.expected_label == "NOT_IN_DOCS" for case in absents)
    assert all(case.reference_answer == "NOT_IN_DOCS" for case in absents)


def test_bilingual_suite_selects_one_language_slice_at_a_time():
    """Select either supported language and reject unknown language names."""
    suite = BilingualSuite(en=(english_case(),), ko=(korean_case(),))

    assert suite.cases("en") == suite.en
    assert suite.cases("ko") == suite.ko
    with pytest.raises(ValueError, match="language"):
        suite.cases("fr")


def test_validate_twin_cases_accepts_the_shipped_suites():
    """Accept the committed English and Korean suites as valid twins."""
    suite = load_bilingual_suites()

    pairs = validate_twin_cases(suite.en, suite.ko)

    assert len(pairs) == CASE_COUNT
    assert [english.id for english, _ in pairs] == sorted(case.id for case in suite.en)


@pytest.mark.parametrize(
    "en_changes, ko_changes, message",
    [
        ({}, {"id": "m3c-02"}, "same cases"),
        ({}, {"category": "simple_lookup", "facet": "factual"}, "category"),
        ({}, {"facet": "risk"}, "facet"),
        ({}, {"tags": ()}, "tags"),
        ({}, {"reference_answer": "매출총이익률이 상승했습니다."}, "reference_answer"),
        (
            {},
            {
                "answers": (
                    GoldenSpan(
                        doc_id="AMD-FY2019",
                        source_sha256=SOURCE_SHA256,
                        start_char=101,
                        end_char=200,
                    ),
                )
            },
            "answers",
        ),
        ({"question": "AMD의 gross margin?"}, {}, "English question contains Hangul"),
        ({}, {"question": "How did gross margin change?"}, "no Hangul"),
    ],
)
def test_validate_twin_cases_rejects_suites_that_could_move_a_metric(
    en_changes, ko_changes, message
):
    """Reject twin drift that could make language metrics incomparable."""
    english = english_case(**en_changes)
    korean = korean_case(**ko_changes)

    with pytest.raises(TwinCaseError, match=message):
        validate_twin_cases((english,), (korean,))


def test_the_twin_invariant_set_covers_every_field_a_suite_could_drift_on():
    """Hold every golden field identical except the join key, question, and note."""
    # ``id`` joins the pair, ``question`` is required to differ, and the shipped Korean
    # notes carry a twin suffix. Everything else — content and provenance alike — is
    # pinned, so adding a field to GoldenCase forces a decision here rather than
    # silently leaving one more axis on which two suites could diverge.
    assert set(TWIN_INVARIANT_FIELDS) | {"id", "question", "note"} == set(GoldenCase.model_fields)

    # The three provenance fields decide how far a suite is trusted rather than what it
    # scores. GoldenCase pins each to a single-value Literal today, so no differing pair
    # can be built; holding them here is what catches a future widening of those types.
    assert {"curation_status", "approval_status", "human_verified"} <= set(TWIN_INVARIANT_FIELDS)


def test_validate_twin_cases_rejects_an_untranslated_or_malformed_suite():
    """Reject untranslated, empty, or duplicate twin suites."""
    english = english_case()

    with pytest.raises(TwinCaseError, match="untranslated"):
        validate_twin_cases((english,), (english,))
    with pytest.raises(TwinCaseError, match="nonempty"):
        validate_twin_cases((), (korean_case(),))
    with pytest.raises(TwinCaseError, match="repeat a case id"):
        validate_twin_cases(
            (english, english),
            (korean_case(), korean_case()),
        )
