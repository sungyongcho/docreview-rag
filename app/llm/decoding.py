"""Strict structured-output parsing, schemas, and bounded repair prompts."""

from __future__ import annotations

from collections.abc import Sequence
from functools import cache
import json
from typing import Any

from openai.types.responses import ResponseFormatTextJSONSchemaConfigParam
from pydantic import BaseModel, ValidationError

from app.llm.schemas import Prompt


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object, rejecting a repeated key instead of merging it."""
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def _invalid_json_constant(value: str) -> None:
    """Reject the non-finite JSON constants a strict schema cannot carry."""
    raise ValueError(f"non-finite JSON number: {value}")


def strict_json_loads(text: str) -> object:
    """Parse strict JSON, rejecting duplicate keys and non-finite numbers.

    Shared by structured-output parsing here and tool-argument parsing in the
    agent loop, so the two strict-JSON notions cannot drift apart.
    """
    return json.loads(
        text,
        object_pairs_hook=_json_object,
        parse_constant=_invalid_json_constant,
    )


def validation_errors(error: ValidationError) -> tuple[str, ...]:
    """Render validation failures as repair instructions the model can act on."""
    messages = []
    for issue in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in issue["loc"]) or "$"
        messages.append(f"{location}: {issue['msg']} [{issue['type']}]")
    return tuple(messages)


def _parse_output[OutputT: BaseModel](
    output_text: str,
    schema: type[OutputT],
) -> tuple[OutputT | None, tuple[str, ...]]:
    """Parse one strict JSON object into the requested output schema.

    Parameters
    ----------
    output_text : str
        Raw provider output.
    schema : type[OutputT]
        Pydantic model required by the caller.

    Returns
    -------
    tuple[OutputT | None, tuple[str, ...]]
        Parsed value with no errors, or ``None`` with stable validation messages.

    Notes
    -----
    The JSON round trip rejects duplicate keys and non-finite numbers while retaining
    JSON-mode strict validation, including array-to-tuple handling.
    """
    try:
        value = strict_json_loads(output_text)
        canonical = json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        return schema.model_validate_json(canonical, strict=True), ()
    except ValidationError as error:
        return None, validation_errors(error)
    except json.JSONDecodeError as error:
        message = f"$: {error.msg} at line {error.lineno} column {error.colno} [json_invalid]"
        return None, (message,)
    except ValueError as error:
        return None, (f"$: {error} [json_invalid]",)


def _repair_prompt(prompt: Prompt, raw_output: str, errors: Sequence[str]) -> Prompt:
    """Extend one prompt with its validation errors and the output that failed."""
    details = "\n".join(f"- {error}" for error in errors)
    return Prompt(
        system=prompt.system,
        user=(
            f"{prompt.user}\n\n"
            "Your previous structured output failed validation. Repair it once and return "
            "only an object that matches the required schema.\n"
            f"Validation errors:\n{details}\n"
            f"Previous output:\n{raw_output}"
        ),
    )


def _strict_schema(node: object, path: str) -> None:
    """Rewrite one JSON-schema node in place to satisfy strict decoding rules."""
    if isinstance(node, list):
        for index, child in enumerate(node):
            _strict_schema(child, f"{path}[{index}]")
        return
    if not isinstance(node, dict):
        return
    for keyword in ("allOf", "oneOf", "not"):
        if keyword in node:
            raise ValueError(f"strict schema does not support {keyword} at {path}")
    # Strict decoding requires every field, so a default can never fire on this
    # surface; it is dropped here rather than rejected so one parameters model can
    # serve both the strict provider schema and tolerant surfaces such as MCP.
    node.pop("default", None)
    if node.get("type") == "object" or "properties" in node:
        node["additionalProperties"] = False
        node["required"] = list(node.get("properties", {}))
    for keyword in ("properties", "$defs"):
        for name, child in node.get(keyword, {}).items():
            _strict_schema(child, f"{path}.{name}")
    for keyword in ("items", "prefixItems", "anyOf"):
        if keyword in node:
            _strict_schema(node[keyword], f"{path}.{keyword}")


@cache
def _strict_schema_json(schema: type[BaseModel]) -> str:
    """Build one strict JSON schema, cached per model class.

    ``model_json_schema`` is neither cached by pydantic nor cheap, and every request
    rebuilds the same payload for the same class. Caching the serialized form rather
    than the dictionary keeps each caller's copy independent of the cache entry. Key
    order is preserved because ``required`` is a positional copy of ``properties``.
    """
    json_schema = schema.model_json_schema()
    _strict_schema(json_schema, "$")
    return json.dumps(json_schema, allow_nan=False, ensure_ascii=False)


def strict_response_format(schema: type[BaseModel]) -> ResponseFormatTextJSONSchemaConfigParam:
    """Return the strict ``text.format`` payload that constrains decoding to one schema.

    Strict structured outputs move schema enforcement from prompting into decoding:
    the API masks every token that would leave the declared JSON schema, so the
    response is guaranteed to parse and to carry exactly the declared keys. The
    guarantee covers syntax and shape only — business invariants such as label and
    citation exclusivity still run in the Pydantic validators downstream.

    Parameters
    ----------
    schema : type[BaseModel]
        Pydantic model describing the required completion payload.

    Returns
    -------
    ResponseFormatTextJSONSchemaConfigParam
        OpenAI ``text.format`` payload with every object closed and required.

    Raises
    ------
    ValueError
        If the generated JSON schema uses a construct strict mode cannot enforce.
    """
    return {
        "type": "json_schema",
        "name": schema.__name__,
        "schema": json.loads(_strict_schema_json(schema)),
        "strict": True,
    }
