"""Shared settings source order for local dotenv-first execution."""

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource


class DotenvFirstSettings(BaseSettings):
    """Prefer explicit init values, then `.env`, then the process environment."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Make a present dotenv value win over a same-named exported variable."""
        del cls, settings_cls
        return init_settings, dotenv_settings, env_settings, file_secret_settings
