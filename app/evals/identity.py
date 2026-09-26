"""Arm naming, ordering, and artifact identity shared by the evaluation commands."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import re
from typing import Any, Final

from app.canonical_json import canonical_json

# Every evaluation command names its arms in lowercase kebab-case, orders them by the
# same retrieval path and ranker precedence, and writes artifacts under the same
# timestamped filename. Holding those three rules in one place is what keeps two
# commands from disagreeing about the order a matrix is reported in, or about what an
# artifact already sitting in ``data/eval_runs`` is called.
ARM_NAME: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
STRATEGY_ORDER: Final[dict[str, int]] = {"lexical": 0, "vector": 1, "hybrid": 2}
RANKER_ORDER: Final[dict[str, int]] = {"ts_rank_cd": 0, "bm25": 1}
RANKER_SLUG: Final[dict[str, str]] = {"ts_rank_cd": "ts-rank-cd", "bm25": "bm25"}
EVALUATED_GOLDEN_KEY: Final[str] = "evaluated_golden_sha256"


def evaluated_golden_sha256(cases: Sequence[Mapping[str, Any]]) -> str:
    """Hash evaluated, source-bound cases independently of JSON key and case order.

    This identifies the exact questions and bound source spans used for scoring.
    The original dataset file digest remains separate provenance and is never rewritten.
    """
    payload = sorted(cases, key=lambda case: case["id"])
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def artifact_filename(recorded_at: datetime, arm_name: str) -> str:
    """Return a UTC-timestamped JSON filename for one arm.

    ``arm_name`` is re-checked here rather than trusted from the caller: it is
    interpolated straight into a path, so a name carrying a separator would place the
    artifact outside the directory the caller chose.

    Raises
    ------
    ValueError
        If ``recorded_at`` is timezone-naive or ``arm_name`` is not kebab-case.
    """
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    if ARM_NAME.fullmatch(arm_name) is None:
        raise ValueError("arm name must be lowercase kebab-case")
    timestamp = recorded_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{arm_name}.json"
