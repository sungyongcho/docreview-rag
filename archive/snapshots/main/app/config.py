from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수(.env) → 설정 객체. 선언한 필드만 매핑하고 나머지(.env의 DB/LLM 키 등)는 무시."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # DATABASE_URL 등 아직 안 쓰는 키가 있어도 에러 안 나게
    )

    # --- 앱 ---
    app_env: str = "local"
    log_level: str = "info"

    # --- 데이터셋 ---
    dataset_root: Path = Path("data/sample1/docreview-dataset/data")

    # --- 임베딩 (Step 3~4) ---
    embedding_provider: Literal["fake", "st"] = "fake"
    embedding_model: str = "all-MiniLM-L6-v2"

    # --- 리랭킹 (Step 7) ---
    rerank_enabled: bool = False
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # --- LLM (Step 10) ---
    primary_llm_provider: Literal["mock", "openai"] = "mock"  # 기본 mock(무과금·결정적)
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    prompt_version: str = "v1"  # 프롬프트 버전 추적 (Step 14 관측성)

    database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"

    @property
    def seed_dir(self) -> Path:
        """정책 마크다운이 있는 디렉토리. parser는 여기서 *.md를 읽는다."""
        return self.dataset_root / "seed" / "synthetic"


@lru_cache
def get_settings() -> Settings:
    """싱글턴. 매번 .env 다시 읽지 않도록 캐시."""
    return Settings()


if __name__ == "__main__":
    s = get_settings()
    print("embedding_provider =", s.embedding_provider)
    print("embedding_model    =", s.embedding_model)
    print("dataset_root       =", s.dataset_root)
    print("seed_dir           =", s.seed_dir, "(exists:", s.seed_dir.exists(), ")")
