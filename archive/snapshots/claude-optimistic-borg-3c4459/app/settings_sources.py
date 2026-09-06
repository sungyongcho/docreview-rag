"""Shared settings source order and OpenAI key-slot resolution for dotenv-first execution."""

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

type Environment = Literal["dev", "prod"]
type KeySlot = Literal["explicit", "dev", "prod"]

# Structured output from a CPU-hosted local model over a full evidence prompt routinely
# runs past a minute, so the default has to let the first attempt finish. It lives here
# rather than beside the provider because importing `app.llm` from settings would drag
# the OpenAI SDK into every process that only wanted to read configuration.
DEFAULT_LOCAL_TIMEOUT_S = 120.0


def _present(value: SecretStr | None) -> SecretStr | None:
    """Treat a blank secret, such as an empty Compose substitution, as absent."""
    if value is None or not value.get_secret_value().strip():
        return None
    return value


def resolve_openai_key(
    *,
    explicit: SecretStr | None,
    dev: SecretStr | None,
    prod: SecretStr | None,
    environment: Environment,
) -> tuple[SecretStr | None, KeySlot | None]:
    """Pick the OpenAI key for one environment and report which slot supplied it.

    An explicit ``OPENAI_API_KEY`` always wins so single-key deployments keep working.
    Otherwise ``MODE=dev`` reads the local slot and ``MODE=prod`` reads the production
    slot, which lets the two environments hold separate project keys and cost limits.
    """
    if _present(explicit) is not None:
        return explicit, "explicit"
    if environment == "dev" and _present(dev) is not None:
        return dev, "dev"
    if environment == "prod" and _present(prod) is not None:
        return prod, "prod"
    return None, None


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
