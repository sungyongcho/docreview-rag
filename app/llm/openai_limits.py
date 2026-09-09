"""Developer-adjustable OpenAI per-call caps kept at or below the configured ceiling."""

import asyncio
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import tempfile
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.llm.schemas import ProviderBudget

DEFAULT_LIMITS_FILE = Path("data/local-settings/openai-limits.json")
# The ceiling comes from ReleaseSettings, whose fields are read with the DOCREVIEW_ prefix.
CEILING_ENV_KEYS: dict[str, str] = {
    "max_input_tokens": "DOCREVIEW_OPENAI_MAX_INPUT_TOKENS",
    "max_output_tokens": "DOCREVIEW_OPENAI_MAX_OUTPUT_TOKENS",
    "max_cost_usd": "DOCREVIEW_OPENAI_MAX_COST_USD",
}
LimitsSource = Literal["ceiling", "saved", "invalid"]


class OpenAILimitsError(ValueError):
    """A safe per-call cap failure suitable for an administrator response."""

    def __init__(self, code: str, message: str) -> None:
        """Keep filesystem details out of messages; name the environment key instead."""
        super().__init__(message)
        self.code = code


class OpenAICallLimits(BaseModel):
    """Effective per-call caps next to the ceiling they may not exceed."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    max_input_tokens: int
    max_output_tokens: int
    max_cost_usd: str
    ceiling_max_input_tokens: int
    ceiling_max_output_tokens: int
    ceiling_max_cost_usd: str
    source: LimitsSource
    editable: bool
    error: str | None = None


class OpenAILimitsManager:
    """Persist working per-call caps for Dev while the ceiling stays a deploy-time setting.

    The ceiling is the ``ProviderBudget`` built from ``.env``; production never reads the
    file and always uses the ceiling. A saved value is clamped on load so an edited file
    cannot raise a cap above the ceiling.
    """

    def __init__(
        self,
        ceiling: ProviderBudget,
        *,
        path: Path = DEFAULT_LIMITS_FILE,
        enabled: bool = True,
    ) -> None:
        self.path = path
        self.enabled = enabled
        self._ceiling = ceiling
        self._effective = ceiling
        self._source: LimitsSource = "ceiling"
        self._error: str | None = None
        self._lock = asyncio.Lock()
        if enabled:
            self._load()

    @property
    def ceiling(self) -> ProviderBudget:
        """Return the deploy-time cap that bounds every saved value."""
        return self._ceiling

    def effective(self) -> ProviderBudget:
        """Return the budget one OpenAI call may spend right now."""
        return self._effective

    def state(self) -> OpenAICallLimits:
        """Describe effective and ceiling values for readiness and settings responses."""
        return OpenAICallLimits(
            max_input_tokens=self._effective.max_input_tokens,
            max_output_tokens=self._effective.max_output_tokens,
            max_cost_usd=str(self._effective.max_cost_usd),
            ceiling_max_input_tokens=self._ceiling.max_input_tokens,
            ceiling_max_output_tokens=self._ceiling.max_output_tokens,
            ceiling_max_cost_usd=str(self._ceiling.max_cost_usd),
            source=self._source,
            editable=self.enabled,
            error=self._error,
        )

    async def save(
        self, *, max_input_tokens: int, max_output_tokens: int, max_cost_usd: Decimal
    ) -> OpenAICallLimits:
        """Validate against the ceiling, persist atomically, then switch the active budget."""
        self._require_enabled()
        async with self._lock:
            candidate = self._validated(max_input_tokens, max_output_tokens, max_cost_usd)
            self._persist(
                {
                    "max_input_tokens": candidate.max_input_tokens,
                    "max_output_tokens": candidate.max_output_tokens,
                    "max_cost_usd": str(candidate.max_cost_usd),
                }
            )
            self._effective = candidate
            self._source = "saved"
            self._error = None
            return self.state()

    async def reset(self) -> OpenAICallLimits:
        """Delete the saved file so the ceiling applies again."""
        self._require_enabled()
        async with self._lock:
            try:
                self.path.unlink(missing_ok=True)
            except PermissionError as error:
                raise OpenAILimitsError(
                    "openai_limits_save_failed",
                    "Could not remove saved OpenAI per-call caps. The settings directory is "
                    "not writable by this runtime user; check its ownership.",
                ) from error
            except OSError as error:
                raise OpenAILimitsError(
                    "openai_limits_save_failed", "Could not remove saved OpenAI per-call caps."
                ) from error
            self._effective = self._ceiling
            self._source = "ceiling"
            self._error = None
            return self.state()

    def _require_enabled(self) -> None:
        """Refuse edits outside Dev; the ceiling is the only production policy."""
        if not self.enabled:
            raise OpenAILimitsError(
                "disabled_in_prod", "OpenAI per-call caps are adjustable only in Dev."
            )

    def _validated(
        self, max_input_tokens: int, max_output_tokens: int, max_cost_usd: Decimal
    ) -> ProviderBudget:
        """Reject values above the ceiling, naming the environment key that raises it."""
        checks: list[tuple[str, Decimal | int, Decimal | int]] = [
            ("max_input_tokens", max_input_tokens, self._ceiling.max_input_tokens),
            ("max_output_tokens", max_output_tokens, self._ceiling.max_output_tokens),
            ("max_cost_usd", max_cost_usd, self._ceiling.max_cost_usd),
        ]
        for name, value, ceiling in checks:
            if value <= 0:
                raise OpenAILimitsError(
                    "openai_limits_invalid", f"{name} must be greater than zero."
                )
            if value > ceiling:
                raise OpenAILimitsError(
                    "openai_limits_above_ceiling",
                    f"{name} may not exceed the ceiling {ceiling}. Raise "
                    f"{CEILING_ENV_KEYS[name]} in .env and restart the stack to allow more.",
                )
        return self._ceiling.model_copy(
            update={
                "max_input_tokens": int(max_input_tokens),
                "max_output_tokens": int(max_output_tokens),
                "max_cost_usd": Decimal(max_cost_usd),
            }
        )

    def _load(self) -> None:
        """Read a saved file once at startup; any problem falls back to the ceiling."""
        try:
            if not self.path.exists():
                return
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict) or data.get("version") != 1:
                raise ValueError("invalid OpenAI per-call cap settings")
            input_tokens = data["max_input_tokens"]
            output_tokens = data["max_output_tokens"]
            if type(input_tokens) is not int or type(output_tokens) is not int:
                raise ValueError("token caps must be integers")
            cost = Decimal(str(data["max_cost_usd"]))
        except PermissionError:
            self._source = "invalid"
            self._error = (
                "Saved OpenAI per-call caps are not readable by this runtime user; "
                "the ceiling applies."
            )
            return
        except OSError, ValueError, TypeError, KeyError, InvalidOperation:
            self._source = "invalid"
            self._error = "Saved OpenAI per-call caps are invalid; the ceiling applies."
            return
        try:
            self._effective = self._validated(input_tokens, output_tokens, cost)
        except OpenAILimitsError as error:
            self._source = "invalid"
            self._error = str(error)
            return
        self._source = "saved"
        self._error = None

    def _persist(self, data: dict[str, object]) -> None:
        """Atomically replace the saved caps before making them active in memory."""
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", dir=self.path.parent, prefix=".openai-limits-", delete=False
            ) as stream:
                temporary = Path(stream.name)
                # The local Compose app uses the host's primary group for host-readable settings.
                os.fchmod(stream.fileno(), 0o640)
                json.dump({"version": 1, **data}, stream)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
        except PermissionError as error:
            raise OpenAILimitsError(
                "openai_limits_save_failed",
                "Could not save OpenAI per-call caps. The settings directory is not "
                "writable by this runtime user; check its ownership.",
            ) from error
        except OSError as error:
            raise OpenAILimitsError(
                "openai_limits_save_failed", "Could not save OpenAI per-call caps."
            ) from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
