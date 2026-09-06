"""Shared settings source order and OpenAI key-slot resolution for dotenv-first execution."""

from typing import Any, Literal

from pydantic import AliasChoices, SecretStr
from pydantic_settings import BaseSettings, InitSettingsSource, PydanticBaseSettingsSource

type Environment = Literal["dev", "prod"]
type KeySlot = Literal["dev", "prod"]

# Structured output from a CPU-hosted local model over a full evidence prompt routinely
# runs past a minute, so the default has to let the first attempt finish. It lives here
# rather than beside the provider because importing `app.llm` from settings would drag
# the OpenAI SDK into every process that only wanted to read configuration.
DEFAULT_LOCAL_TIMEOUT_S = 120.0
DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:11434"


def _present(value: SecretStr | None) -> SecretStr | None:
    """Treat a blank secret, such as an empty Compose substitution, as absent."""
    if value is None or not value.get_secret_value().strip():
        return None
    return value


def resolve_openai_key(
    *,
    dev: SecretStr | None,
    prod: SecretStr | None,
    environment: Environment,
) -> tuple[SecretStr | None, KeySlot | None]:
    """Pick the OpenAI key for one environment and report which slot supplied it.

    ``MODE=dev`` reads only the local slot and ``MODE=prod`` reads only the production
    slot. A missing slot never falls back to another environment's credentials.
    """
    if environment == "dev" and _present(dev) is not None:
        return dev, "dev"
    if environment == "prod" and _present(prod) is not None:
        return prod, "prod"
    return None, None


class DotenvFirstSettings(BaseSettings):
    """Preserve dotenv-first settings except for command controls and local endpoints."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Let explicit process controls win without changing credential precedence."""
        del cls
        process_first = {
            "environment",
            "mode",
            "admin_mode",
            "allow_ingest",
            "trust_proxy_headers",
            "local_llm_base_url",
            "local_llm_protocol",
        }

        def merged_settings() -> dict[str, Any]:
            """Combine sources once, preserving aliases and reporting endpoint provenance."""
            environment = env_settings()
            dotenv = dotenv_settings()
            values = {**environment, **dotenv}
            for name in process_first:
                field = settings_cls.model_fields.get(name)
                if field is None:
                    continue
                alias = field.validation_alias
                aliases = alias.choices if isinstance(alias, AliasChoices) else [alias or name]
                keys = [key for key in [name, *aliases] if isinstance(key, str)]
                selected = next((key for key in keys if key in environment), None)
                if selected is not None:
                    for key in keys:
                        values.pop(key, None)
                    values[selected] = environment[selected]
                if name == "local_llm_base_url":
                    source = (
                        "environment"
                        if selected is not None
                        else "dotenv"
                        if any(key in dotenv for key in keys)
                        else "default"
                    )
                    values["local_llm_source"] = source
            return values

        class MergedSettingsSource(InitSettingsSource):
            """Expose merged aliases unchanged through the framework source interface."""

            def __call__(self) -> dict[str, Any]:
                """Evaluate the original merge without reinterpreting field aliases."""
                return merged_settings()

        return init_settings, MergedSettingsSource(settings_cls, {}), file_secret_settings
