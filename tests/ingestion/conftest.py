"""`app/ingestion` 테스트 설비.

**여기 있는 픽스처는 전부 코퍼스(`data/corpus/`)에 묶여 있다.** 그래서 루트가 아니라
이 디렉터리에 둔다 — 원칙은 "픽스처는 그것을 쓰는 테스트가 **전부** 아래에 있는
가장 얕은 디렉터리에 산다". retrieval·eval 테스트가 생겨도 이 픽스처들을 상속받을
이유가 없다.

**단계별로 켜지는 구조.** 아직 안 만든 함수를 쓰는 테스트는 실패가 아니라 skip이라,
`pytest` 출력이 그대로 진행 상황판이 된다.

The zero branch grades canonical implementation paths directly.
"""

import importlib
import json
import os
from pathlib import Path

import pytest

from tests.support import need

MODULE_NAME = os.getenv("PARSER_MODULE", "app.ingestion.parser")
TABLES_MODULE_NAME = os.getenv("TABLES_MODULE", "app.ingestion.tables")


@pytest.fixture(scope="session")
def P():
    """테스트 대상 모듈. `PARSER_MODULE` 환경변수로 바꾼다."""
    return importlib.import_module(MODULE_NAME)


@pytest.fixture(scope="session")
def T():
    """표 변환 모듈. `TABLES_MODULE`로 바꾼다 — `P`와 같은 규약이다.

    영역마다 스위치를 하나씩 두는 게 원칙이다. 파서를 다 짠 사람이 표 변환만
    새로 짜볼 수 있어야 하고, 그 반대도 돼야 한다.
    """
    return importlib.import_module(TABLES_MODULE_NAME)


@pytest.fixture(scope="session")
def manifest() -> list[dict]:
    path = Path("data/corpus/manifest.json")
    if not path.exists():
        pytest.skip("data/corpus/manifest.json 없음 — M0을 먼저 돌려라")
    return json.loads(path.read_text())


def doc_id(entry: dict) -> str:
    return f"{entry['ticker']}-FY{entry['report_date'][:4]}"


@pytest.fixture(scope="session")
def blocks_by_doc(P, manifest) -> dict[str, tuple]:
    """문서별 (soup, blocks, raw). 세션당 한 번만 파싱한다(20개 약 18초)."""
    need(P, "normalize", "leaf_blocks")
    out = {}
    for e in manifest:
        raw = Path(e["file"]).read_text(encoding="utf-8")
        soup = P.normalize(raw)
        out[doc_id(e)] = (soup, P.leaf_blocks(soup), raw)
    return out


@pytest.fixture(scope="session")
def profiles_dir(tmp_path_factory) -> Path:
    """부트스트랩이 프로파일을 써 넣을 임시 디렉터리.

    `parsed`가 여기에 학습 결과를 남기므로, 프로파일 I/O 테스트가 20문서를
    다시 파싱하지 않고 결과물을 그대로 들여다볼 수 있다.
    """
    return tmp_path_factory.mktemp("profiles")


@pytest.fixture(scope="session")
def parsed(P, manifest, profiles_dir) -> dict:
    """문서별 ParsedFiling. 프로파일은 임시 디렉터리에 새로 학습한다.

    `data/profiles`를 건드리지 않는 게 중요하다 — 테스트가 실행 순서나
    남아 있던 상태에 따라 달라지면 회귀 테스트로서 의미가 없다.
    """
    need(P, "parse_filing", "PROFILES")
    original = P.PROFILES
    P.PROFILES = profiles_dir
    try:
        out = {}
        for e in sorted(manifest, key=lambda x: (x["ticker"], x["report_date"])):
            r = P.parse_filing(e)
            out[doc_id(e)] = r[0] if isinstance(r, tuple) else r
        return out
    finally:
        P.PROFILES = original
