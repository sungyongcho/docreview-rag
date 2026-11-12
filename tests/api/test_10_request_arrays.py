"""Check that every strict request body takes what JSON can carry for its fields."""

from collections.abc import Iterator
import dataclasses
from ipaddress import IPv4Address
import json
from pathlib import Path
import sys
import typing

from pydantic import (
    AfterValidator,
    AnyUrl,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    SecretStr,
    create_model,
)
import pytest

from app.api.app import PROD_SURFACE, create_api_app
from app.contracts.validation import StrictSchema, tuple_from_json_array

# What a compiled validator does with the value a decoded JSON body holds for it. A kind
# named in none of these groups is reported wherever it appears, so a field type nobody
# has classified here cannot pass unread.
# Kinds that take that value in every mode.
ACCEPTED = frozenset(
    {"any", "str", "int", "float", "bool", "none", "list", "dict", "literal", "url"}
    # A plain function receives the value itself and holds no validator to read.
    | {"function-plain"}
)
# Kinds that refuse it in strict mode: an array for the first group, a string or an
# object for the second.
ARRAYS = frozenset({"tuple", "set", "frozenset"})
OTHERS = frozenset(
    {"date", "datetime", "time", "timedelta", "uuid", "decimal", "bytes", "enum", "dataclass"}
)
# Kinds that only arrange other validators, which are read in turn.
HOLDERS = frozenset(
    {
        "model",
        "model-fields",
        "model-field",
        "typed-dict",
        "typed-dict-field",
        "dataclass-args",
        "dataclass-field",
        "default",
        "nullable",
        "union",
        "definitions",
        "definition-ref",
        "function-before",
        "function-after",
        "function-wrap",
        "lax-or-strict",
        "json-or-python",
    }
)
# Wrappers that hand their input on unchanged, so a validator placed before them still
# decides what the wrapped type receives.
TRANSPARENT = frozenset({"default", "nullable", "union", "function-after"})
# One value of every type a decoded JSON body can hold.
JSON_VALUES = ("", 0, 0.0, True, None, [], {})
# Entries of a validator that are not validators, whatever they look like.
NOT_VALIDATORS = frozenset(
    {
        "cls",
        "metadata",
        "function",
        "config",
        "serialization",
        "default",
        "expected",
        "ref",
        "schema_ref",
        "discriminator",
    }
)


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


def _validated_classes(names: set[str]) -> list[type]:
    """Return every loaded application class with a compiled validator and a listed name."""
    found: dict[int, type] = {}
    for module_name, module in list(sys.modules.items()):
        if module_name != "app" and not module_name.startswith("app."):
            continue
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and "__pydantic_core_schema__" in vars(value)
                and (value.__name__ in names or f"{value.__name__}-Input" in names)
            ):
                found[id(value)] = value
    return sorted(found.values(), key=lambda cls: (cls.__module__, cls.__qualname__))


def _refusals(
    node: object,
    *,
    strict: bool,
    admitted: bool,
    path: str,
    shared: dict[str, object],
    seen: set[tuple[str, bool, bool]],
) -> Iterator[str]:
    """Yield the places in a compiled validator that refuse a decoded JSON value.

    A validator of a kind this module does not classify is yielded as well: what it does
    with a JSON value is unknown until someone reads it and names it in a group above.
    ``strict`` is the mode in force at the node, and ``admitted`` is whether a validator
    directly before it already turns a JSON array into a tuple. ``shared`` holds the
    validators the schema defines once and refers to by name; each is read in the mode of
    every place that refers to it, and ``seen`` holds the ones being read, so that a
    validator that refers to itself is not read without end.
    """

    def below(child: object, *, admitted: bool = False, path: str = path) -> Iterator[str]:
        """Read one child in the mode in force here."""
        return _refusals(
            child, strict=strict, admitted=admitted, path=path, shared=shared, seen=seen
        )

    if isinstance(node, list | tuple):
        for child in node:
            yield from below(child, admitted=admitted)
        return
    if not isinstance(node, dict):
        return
    kind = node.get("type")
    if not isinstance(kind, str):
        # A plain mapping, such as the fields of a model: its keys name the way down.
        for name, child in node.items():
            yield from below(child, path=f"{path}.{name}")
        return
    if kind == "definitions":
        yield from below(node["schema"], admitted=admitted)
        return
    if kind == "definition-ref":
        visit = (node["schema_ref"], strict, admitted)
        if visit not in seen:
            seen.add(visit)
            yield from below(shared[node["schema_ref"]], admitted=admitted)
            seen.discard(visit)
        return
    config = node.get("config")
    if kind == "model":
        # A model validates in its own mode, whatever the model around it uses.
        strict = bool((config or {}).get("strict", False))
    elif isinstance(config, dict) and "strict" in config:
        strict = bool(config["strict"])
    refuses = bool(node.get("strict", strict))
    if kind == "lax-or-strict":
        # Only the branch of the mode in force ever sees the value.
        yield from below(node["strict_schema" if refuses else "lax_schema"])
        return
    if kind == "json-or-python":
        # A request body reaches its model already decoded, as Python values.
        yield from below(node["python_schema"])
        return
    if kind == "union":
        choices = [choice[0] if isinstance(choice, tuple) else choice for choice in node["choices"]]
        # An instance check beside another choice only lets a ready-made object
        # through; a JSON value takes the other choice.
        open_to_json = [choice for choice in choices if choice.get("type") != "is-instance"]
        yield from below(open_to_json or choices, admitted=admitted)
        return
    if kind == "is-instance":
        if not any(isinstance(value, node["cls"]) for value in JSON_VALUES):
            yield f"{path} ({kind})"
        return
    if kind in ARRAYS:
        if refuses and not admitted:
            yield f"{path} ({kind})"
    elif kind in OTHERS:
        if refuses:
            yield f"{path} ({kind})"
    elif kind == "literal":
        if not all(isinstance(value, str | int | float | None) for value in node["expected"]):
            yield f"{path} ({kind})"
    elif kind == "dict":
        keys = node.get("keys_schema", {}).get("type", "any")
        if refuses and keys not in {"str", "any"}:
            # A JSON object names its members with strings.
            yield f"{path} (dict key {keys})"
    elif kind not in ACCEPTED | HOLDERS:
        yield f"{path} ({kind})"
    passes_on = (
        kind == "function-before" and node["function"]["function"] is tuple_from_json_array
    ) or (kind in TRANSPARENT and admitted)
    for name, child in node.items():
        if name not in NOT_VALIDATORS:
            yield from _refusals(
                child, strict=strict, admitted=passes_on, path=path, shared=shared, seen=seen
            )


def _all_refusals(cls: type) -> list[str]:
    """List where one class's compiled validator refuses a decoded JSON value.

    The class itself may be given as a JSON object, so only what is inside it counts.
    """
    schema = vars(cls)["__pydantic_core_schema__"]
    shared = {
        definition["ref"]: definition
        for definition in (schema.get("definitions", ()) if schema["type"] == "definitions" else ())
    }
    name = cls.__name__
    places = set(
        _refusals(schema, strict=False, admitted=False, path=name, shared=shared, seen=set())
    )
    return sorted(places - {f"{name} (dataclass)"})


def test_strict_request_bodies_take_what_json_carries():
    """A strict request model refuses a JSON array or string unless the field admits it."""
    names = _request_schema_names(create_api_app(surface=PROD_SURFACE).openapi())
    classes = _validated_classes(names)

    refusing = [place for cls in classes for place in _all_refusals(cls)]

    assert refusing == []
    assert {"AmendmentReviewRequest", "ReviewRequest", "EvidenceSelection", "AdminCommand"} <= {
        cls.__name__ for cls in classes
    }


def test_the_check_finds_a_refusal_wherever_the_field_type_hides_it():
    """Aliases, mapping values, nested arrays, sets and any strict model are all read."""
    type Ids = tuple[int, ...]
    admitted = BeforeValidator(tuple_from_json_array)

    @dataclasses.dataclass
    class Point:
        """A plain dataclass, which a strict model takes only as an instance."""

        x: int

    class Shared(BaseModel):
        """A strict model that uses one alias twice, so the tuple is defined once apart."""

        model_config = ConfigDict(strict=True)

        first: Ids
        second: Ids
        point: Point

    class Probe(BaseModel):
        """A strict model that is not a ``StrictSchema``."""

        model_config = ConfigDict(strict=True)

        aliased: Ids
        by_name: dict[str, tuple[int, ...]]
        nested: typing.Annotated[tuple[tuple[int, ...], ...], admitted]
        unordered: frozenset[int]
        optional: typing.Annotated[tuple[int, ...] | None, admitted] = None

    class Lenient(BaseModel):
        """A model that coerces, inside which a strict one keeps its own mode."""

        ids: tuple[int, ...]
        inner: Probe

    class Admitted(StrictSchema):
        """A strict model whose only array field admits arrays."""

        ids: typing.Annotated[tuple[int, ...], admitted] = ()

    assert _all_refusals(Probe) == [
        "Probe.aliased (tuple)",
        "Probe.by_name (tuple)",
        "Probe.nested (tuple)",
        "Probe.unordered (frozenset)",
    ]
    assert _all_refusals(Lenient) == [
        f"Lenient.inner.{place.removeprefix('Probe.')}" for place in _all_refusals(Probe)
    ]
    assert _all_refusals(Admitted) == []
    assert _all_refusals(Shared) == [
        "Shared.first (tuple)",
        "Shared.point (dataclass)",
        "Shared.second (tuple)",
    ]
    for body in (
        {"first": [1], "second": (1,), "point": Point(1)},
        {"first": (1,), "second": (1,), "point": {"x": 1}},
    ):
        try:
            Shared.model_validate(body)
        except ValueError:
            continue
        raise AssertionError(f"the strict probe accepted {body}")
    # The check agrees with what the models do with a decoded JSON body.
    Admitted.model_validate({"ids": [1, 2]})
    Lenient.model_validate({"ids": [1], "inner": Probe(**_probe_values()).model_dump()})


def _unchanged(value: object) -> object:
    """Stand in for a validator that checks a value and hands it back."""
    return value


@pytest.mark.parametrize(
    ("annotation", "value", "refusals"),
    [
        # A validator that runs after the tuple is built does not undo the admission.
        (
            typing.Annotated[
                tuple[int, ...],
                AfterValidator(_unchanged),
                BeforeValidator(tuple_from_json_array),
            ],
            [1],
            [],
        ),
        (dict[str, int], {"a": 1}, []),
        (dict[int, str], {"1": "a"}, ["Body.value (dict key int)"]),
        (typing.Literal["a", 1], "a", []),
        (AnyUrl, "https://example.com/", []),
        (SecretStr, "secret", []),
        (IPv4Address, "192.0.2.1", ["Body.value (is-instance)"]),
        (Path, "a/b", ["Body.value (is-instance)"]),
        # A kind no group names is reported, whatever it would do with the value.
        (complex, "1+2j", ["Body.value (complex)"]),
    ],
)
def test_the_check_agrees_with_what_a_strict_model_does(
    annotation: typing.Any, value: object, refusals: list[str]
) -> None:
    """A field type is reported exactly when its strict model refuses the JSON value."""
    model = create_model("Body", __config__=ConfigDict(strict=True), value=(annotation, ...))
    body = json.loads(json.dumps({"value": value}))

    assert _all_refusals(model) == refusals
    if refusals:
        with pytest.raises(ValueError):
            model.model_validate(body)
    else:
        model.model_validate(body)


def _probe_values() -> dict[str, object]:
    """Give the probe model values of the exact types its strict fields require."""
    return {
        "aliased": (1,),
        "by_name": {"a": (1,)},
        "nested": ((1,),),
        "unordered": frozenset({1}),
    }
