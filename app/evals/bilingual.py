"""Paired Korean and English golden suites over one immutable set of answer spans."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import re

from app.evals.loader import (
    DEFAULT_GOLDEN_PATH,
    DEFAULT_MANIFEST_PATH,
    REPO_ROOT,
    load_golden_cases,
)
from app.evals.types import GoldenCase

KO_GOLDEN_PATH = REPO_ROOT / "data" / "golden" / "retrieval_ko.json"

# The twin validator only has to answer "is there Korean text here", so it scans for
# Hangul directly instead of importing the M8.3 routing detector: the suite contract
# must hold before any query-path code exists, and a shared helper would make the
# first checkpoint depend on the third.
HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")

# Every field a retrieval metric could be attributed to. Holding all of them identical
# is what makes an en/ko metric gap a fact about retrieval rather than about the data.
TWIN_INVARIANT_FIELDS = (
    "category",
    "facet",
    "tags",
    "answers",
    "expected_label",
    "reference_answer",
)


class TwinCaseError(ValueError):
    """A Korean suite is not a faithful twin of its English counterpart."""


@dataclass(frozen=True, slots=True)
class BilingualSuite:
    """One English suite and its validated Korean twin, in shared case-id order."""

    en: tuple[GoldenCase, ...]
    ko: tuple[GoldenCase, ...]

    def pairs(self) -> tuple[tuple[GoldenCase, GoldenCase], ...]:
        """Return ``(en, ko)`` case pairs ordered by their shared id."""
        by_id = {case.id: case for case in self.ko}
        return tuple((case, by_id[case.id]) for case in self.en)

    def cases(self, language: str) -> tuple[GoldenCase, ...]:
        """Return the suite for one language, so a run can name its slice."""
        if language == "en":
            return self.en
        if language == "ko":
            return self.ko
        raise ValueError(f"unsupported suite language: {language}")


def _normalized(question: str) -> str:
    """Casefold one question and collapse its whitespace for identity comparison."""
    return " ".join(question.casefold().split())


def validate_twin_cases(
    en_cases: Sequence[GoldenCase],
    ko_cases: Sequence[GoldenCase],
) -> tuple[tuple[GoldenCase, GoldenCase], ...]:
    """Validate that two suites differ in exactly one field, and return id-ordered pairs.

    Twin cases share their ids, their taxonomy, and — decisively — their answer spans,
    so a Korean run and an English run are scored against the same immutable source
    coordinates. That is the whole reason the parity number means anything: if the
    suites could drift, a ko/en gap would be ambiguous between "retrieval is worse in
    Korean" and "the Korean cases ask something easier".

    ``reference_answer`` stays English on both sides. Retrieval scoring never reads it,
    and requiring identity makes the invariant checkable instead of approximate.

    The two suites must live in separate files. ``load_golden_cases`` rejects duplicate
    answer-span identities inside one loaded batch, and twins share every span by
    design, so loading a directory that holds both raises before this validator runs.
    """
    if not en_cases or not ko_cases:
        raise TwinCaseError("both twin suites must be nonempty")

    en_index = {case.id: case for case in en_cases}
    ko_index = {case.id: case for case in ko_cases}
    if len(en_index) != len(en_cases) or len(ko_index) != len(ko_cases):
        raise TwinCaseError("twin suites must not repeat a case id")
    if set(en_index) != set(ko_index):
        missing = sorted(set(en_index) ^ set(ko_index))
        raise TwinCaseError(f"twin suites do not cover the same cases: {', '.join(missing)}")

    pairs: list[tuple[GoldenCase, GoldenCase]] = []
    for case_id in sorted(en_index):
        english = en_index[case_id]
        korean = ko_index[case_id]
        for field in TWIN_INVARIANT_FIELDS:
            if getattr(english, field) != getattr(korean, field):
                raise TwinCaseError(f"{case_id} twins disagree about {field}")
        # Checked before the script rules: a copied-across question is the likely
        # authoring slip, and reporting it as "no Hangul" would name the symptom.
        if _normalized(english.question) == _normalized(korean.question):
            raise TwinCaseError(f"{case_id} twins share one untranslated question")
        if HANGUL.search(english.question) is not None:
            raise TwinCaseError(f"{case_id} English question contains Hangul")
        if HANGUL.search(korean.question) is None:
            raise TwinCaseError(f"{case_id} Korean question contains no Hangul")
        pairs.append((english, korean))
    return tuple(pairs)


def load_bilingual_suites(
    en_path: str | Path = DEFAULT_GOLDEN_PATH,
    ko_path: str | Path = KO_GOLDEN_PATH,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> BilingualSuite:
    """Load both suites through the unmodified loader and validate them as twins.

    Two separate ``load_golden_cases`` calls, not one directory load: each file gets
    the loader's full SHA-256 and span-source verification, and the Korean file is
    bound to the same raw filings as the English one, for free.
    """
    en_cases = load_golden_cases(en_path, manifest_path=manifest_path)
    ko_cases = load_golden_cases(ko_path, manifest_path=manifest_path)
    pairs = validate_twin_cases(en_cases, ko_cases)
    return BilingualSuite(
        en=tuple(english for english, _ in pairs),
        ko=tuple(korean for _, korean in pairs),
    )
