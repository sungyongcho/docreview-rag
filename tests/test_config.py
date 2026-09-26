"""Environment parsing preserves the fixed embedding schema contract."""

from pydantic import ValidationError
import pytest

from app.config import Settings
from tests.support import load_settings


def test_compose_embedding_dimension_accepts_the_fixed_environment_value(monkeypatch):
    """Docker environment variables are strings even when Compose quotes a numeric value."""
    monkeypatch.setenv("EMBED_DIM", "384")
    assert load_settings(Settings, env_file=None).embed_dim == 384


@pytest.mark.parametrize("value", ["768", "384.0", "invalid"])
def test_embedding_dimension_still_rejects_other_values(monkeypatch, value):
    """Do not widen the model or database dimension while accepting normal env parsing."""
    monkeypatch.setenv("EMBED_DIM", value)
    with pytest.raises(ValidationError):
        load_settings(Settings, env_file=None)
