"""Check that every strict request body takes the JSON arrays its contract declares."""

import types
import typing

from pydantic import BaseModel, BeforeValidator

from app.api.app import PROD_SURFACE, create_api_app
from app.contracts.validation import StrictSchema, tuple_from_json_array


def _request_schema_names(document: dict[str, typing.Any]) -> set[str]:
    """Name every component schema reachable from a request body of the API document."""
    components = document["components"]["schemas"]
    names: set[str] = set()

    def visit(node: object) -> None:
        """Follow references through one schema node."""
        if isinstance(node, dict):
            reference = node.get("$ref")
            if isinstance(reference, str):
                name = reference.rsplit("/", 1)[-1]
                if name not in names:
                    names.add(name)
                    visit(components[name])
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    for path in document["paths"].values():
        for operation in path.values():
            if isinstance(operation, dict):
                visit(operation.get("requestBody"))
    return names


def _strict_models(base: type[BaseModel]) -> list[type[BaseModel]]:
    """Return every loaded strict schema below the given class."""
    found: list[type[BaseModel]] = []
    for model in base.__subclasses__():
        found.extend([model, *_strict_models(model)])
    return found


def _holds_tuple(annotation: object) -> bool:
    """Tell whether a field annotation is a tuple, alone or as one alternative."""
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        return _holds_tuple(typing.get_args(annotation)[0])
    if origin in (typing.Union, types.UnionType):
        return any(_holds_tuple(argument) for argument in typing.get_args(annotation))
    return origin is tuple


def test_strict_request_bodies_take_json_arrays_for_their_tuples():
    """A strict model refuses a JSON array for a tuple unless the field admits arrays."""
    names = _request_schema_names(create_api_app(surface=PROD_SURFACE).openapi())
    refusing = sorted(
        f"{model.__name__}.{name}"
        for model in _strict_models(StrictSchema)
        if model.__name__ in names or f"{model.__name__}-Input" in names
        for name, field in model.model_fields.items()
        if _holds_tuple(field.annotation)
        and not any(
            isinstance(entry, BeforeValidator) and entry.func is tuple_from_json_array
            for entry in field.metadata
        )
    )

    assert refusing == []
    assert {"AmendmentReviewRequest", "ReviewRequest", "EvidenceSelection"} <= names
