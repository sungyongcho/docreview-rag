"""Strict scalar and immutable input contracts shared by application domains."""

from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr


def reject_blank(value: str) -> str:
    """Reject text that is present but carries no visible character."""
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


def tuple_from_json_array(value: object) -> object:
    """Accept JSON arrays without coercing their child values or other input types."""
    return tuple(value) if isinstance(value, list) else value


NonBlank = Annotated[StrictStr, Field(min_length=1), AfterValidator(reject_blank)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
FiniteFloat = Annotated[StrictFloat, Field(allow_inf_nan=False)]
NonNegativeFloat = Annotated[StrictFloat, Field(ge=0, allow_inf_nan=False)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class StrictSchema(BaseModel):
    """Reject coercion and unknown fields in immutable boundary values."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
