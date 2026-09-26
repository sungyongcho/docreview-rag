"""Provider settings and source precedence shared by CLI and HTTP runtimes."""

from typing import Any, Literal, cast

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import (
    BaseSettings,
    InitSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

type Environment = Literal["dev", "prod"]

# CPU-hosted structured output over a full evidence prompt can take over a minute.
DEFAULT_LOCAL_TIMEOUT_S = 120.0
DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:11434"


class ProviderSettings(BaseSettings):
    """Own provider inputs, credential selection, and dotenv/process precedence."""

    model_config = SettingsConfigDict(validate_by_name=True)

    # MODE selects an isolated development or production credential slot.
    environment: Environment = Field(default="dev", validation_alias="MODE")
    openai_api_key_dev: SecretStr | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY_LOCAL",
    )
    openai_api_key_prod: SecretStr | None = Field(
        default=None, validation_alias="OPENAI_API_KEY_PROD"
    )
    local_llm_base_url: str | None = Field(
        default=DEFAULT_LOCAL_BASE_URL,
        validation_alias="LOCAL_LLM_BASE_URL",
    )
    local_llm_source: Literal["environment", "dotenv", "default"] = Field(
        default="default", validation_alias="local_llm_source", exclude=True
    )
    local_llm_protocol: Literal["auto", "openai_responses", "ollama"] = Field(
        default="auto",
        validation_alias="LOCAL_LLM_PROTOCOL",
    )
    local_llm_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="LOCAL_LLM_API_KEY",
    )
    # These carry an explicit bare alias because `env_prefix` alone would only accept the
    # prefixed spelling, while Compose forwards the bare `LOCAL_LLM_*` names.
    local_llm_max_input_tokens: int = Field(
        default=12_000,
        gt=0,
        validation_alias="LOCAL_LLM_MAX_INPUT_TOKENS",
    )
    local_llm_max_output_tokens: int = Field(
        default=600,
        gt=0,
        validation_alias="LOCAL_LLM_MAX_OUTPUT_TOKENS",
    )
    local_llm_timeout_s: float = Field(
        default=DEFAULT_LOCAL_TIMEOUT_S,
        gt=0,
        le=600,
        validation_alias="LOCAL_LLM_TIMEOUT_S",
    )

    @field_validator(
        "local_llm_max_input_tokens",
        "local_llm_max_output_tokens",
        "local_llm_timeout_s",
        mode="before",
    )
    @classmethod
    def blank_local_numbers_use_defaults(cls, value: object, info: ValidationInfo) -> object:
        """Fall back to the field default when Compose substitutes an unset numeric key."""
        if isinstance(value, str) and not value.strip():
            return cls.model_fields[str(info.field_name)].default
        return value

    @field_validator(
        "openai_api_key_dev",
        "openai_api_key_prod",
        "local_llm_base_url",
        "local_llm_api_key",
        mode="before",
    )
    @classmethod
    def blank_key_is_unset(cls, value: object) -> object:
        """Treat blank compose substitutions as an absent provider secret."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def openai_api_key(self) -> SecretStr | None:
        """Select only the MODE credential slot; blank secrets never enable a provider."""
        key = self.openai_api_key_dev if self.environment == "dev" else self.openai_api_key_prod
        return key if key is not None and key.get_secret_value().strip() else None

    @property
    def openai_key_slot(self) -> Environment | None:
        """Name the selected credential slot without storing duplicate derived state."""
        return self.environment if self.openai_api_key is not None else None

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
            "service_mode",
            "admin_mode",
            "trust_proxy_headers",
            "local_llm_base_url",
            "local_llm_protocol",
        }

        class MergedSettingsSource(InitSettingsSource):
            """Merge process controls once while preserving dotenv credential precedence."""

            def __call__(self) -> dict[str, Any]:
                """Preserve source aliases and record local endpoint provenance."""
                environment = env_settings()
                dotenv = dotenv_settings()
                values = {**environment, **dotenv}
                for name in process_first:
                    field = settings_cls.model_fields.get(name)
                    if field is None:
                        continue
                    keys = (name, cast(str, field.validation_alias or name))
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

        return init_settings, MergedSettingsSource(settings_cls, {}), file_secret_settings
