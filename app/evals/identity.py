"""Arm naming, ordering, and artifact identity shared by the evaluation commands."""

from datetime import UTC, datetime
import re
from typing import Final

# Every evaluation command names its arms in lowercase kebab-case, orders them by the
# same retrieval path and ranker precedence, and writes artifacts under the same
# timestamped filename. Holding those three rules in one place is what keeps two
# commands from disagreeing about the order a matrix is reported in, or about what an
# artifact already sitting in ``data/eval_runs`` is called.
ARM_NAME: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
STRATEGY_ORDER: Final[dict[str, int]] = {"lexical": 0, "vector": 1, "hybrid": 2}
RANKER_ORDER: Final[dict[str, int]] = {"ts_rank_cd": 0, "bm25": 1}
RANKER_SLUG: Final[dict[str, str]] = {"ts_rank_cd": "ts-rank-cd", "bm25": "bm25"}


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
