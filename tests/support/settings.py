"""Settings construction shared by the configuration, CLI and release tests."""

from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings


def load_settings[SettingsT: BaseSettings](
    settings_type: type[SettingsT], /, *, env_file: Path | None, **values: Any
) -> SettingsT:
    """Build settings from one dotenv file, or none, plus explicit init values.

    Pyright derives each settings class's constructor from its field names, so it rejects
    BaseSettings' `_env_file` argument and the environment-variable aliases such as `MODE`
    that tests pass on purpose. Calling through `type[SettingsT]` checks the call against
    the BaseSettings constructor that actually runs.
    """
    return settings_type(_env_file=env_file, **values)
