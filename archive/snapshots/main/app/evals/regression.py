import json
from pathlib import Path

BASELINE = Path("evals/baseline.json")


def save_baseline(metrics: dict, path: Path = BASELINE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, indent=2))


def load_baseline(path: Path = BASELINE) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def compare(prev: dict, curr: dict) -> dict:
    """지표별 델타. 음수면 회귀."""
    return {
        k: {
            "prev": prev.get(k),
            "curr": curr[k],
            "delta": round(curr[k] - prev.get(k, 0.0), 4),
        }
        for k in curr
    }
