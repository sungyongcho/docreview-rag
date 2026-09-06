"""Module-switch fixtures for the M8 learner harness.

Every M8 checkpoint adds its own file, so this harness has five switches rather than
one. Each is loaded through ``optional_module``: before a checkpoint is written, its
tests skip instead of failing collection for the whole directory.
"""

import os
from types import ModuleType

import pytest

from tests.support import optional_module

DEFAULT_BILINGUAL_MODULE = "app.evals.bilingual"
DEFAULT_CROSSLINGUAL_MODULE = "app.evals.crosslingual"
DEFAULT_LANGUAGE_MODULE = "app.retrieval.language"
DEFAULT_TRANSLATE_MODULE = "app.retrieval.translate"
DEFAULT_PARITY_MODULE = "app.evals.parity"


def load_checkpoint_module(variable: str, default: str) -> ModuleType:
    """Load the checkpoint module named by one environment variable."""
    return optional_module(os.getenv(variable, default))


@pytest.fixture(scope="session")
def BI() -> ModuleType:
    """Bilingual twin-suite module selected by ``BILINGUAL_MODULE``."""
    return load_checkpoint_module("BILINGUAL_MODULE", DEFAULT_BILINGUAL_MODULE)


@pytest.fixture(scope="session")
def XL() -> ModuleType:
    """Cross-lingual arm module selected by ``CROSSLINGUAL_MODULE``."""
    return load_checkpoint_module("CROSSLINGUAL_MODULE", DEFAULT_CROSSLINGUAL_MODULE)


@pytest.fixture(scope="session")
def LANG() -> ModuleType:
    """Query-language detection module selected by ``LANGUAGE_MODULE``."""
    return load_checkpoint_module("LANGUAGE_MODULE", DEFAULT_LANGUAGE_MODULE)


@pytest.fixture(scope="session")
def TR() -> ModuleType:
    """Query-translation module selected by ``TRANSLATE_MODULE``."""
    return load_checkpoint_module("TRANSLATE_MODULE", DEFAULT_TRANSLATE_MODULE)


@pytest.fixture(scope="session")
def PAR() -> ModuleType:
    """Parity-gate module selected by ``PARITY_MODULE``."""
    return load_checkpoint_module("PARITY_MODULE", DEFAULT_PARITY_MODULE)
