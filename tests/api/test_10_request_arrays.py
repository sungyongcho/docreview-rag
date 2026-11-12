"""Check that every strict request body takes what JSON can carry for its fields."""

from collections.abc import Iterator
import dataclasses
import sys
import typing

from pydantic import BaseModel, BeforeValidator, ConfigDict

from app.api.app import PROD_SURFACE, create_api_app
from app.contracts.validation import StrictSchema, tuple_from_json_array

# Compiled validators that refuse, in strict mode, the value a decoded JSON body holds
# for them: an array for the first group, a string or an object for the second.
ARRAYS = frozenset({"tuple", "set", "frozenset"})
OTHERS = frozenset(
    {
        "date",
        "datetime",
        "time",
        "timedelta",
        "uuid",
        "decimal",
        "bytes",
        "enum",
        "url",
        "dataclass",
    }
)
# Wrappers that hand their input on unchanged, so a validator placed before them still
# decides what the wrapped type receives.
TRANSPARENT = frozenset({"default", "nullable", "union"})


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
    if (kind in ARRAYS and refuses and not admitted) or (kind in OTHERS and refuses):
        yield f"{path} ({kind})"
    passes_on = (
        kind == "function-before" and node["function"]["function"] is tuple_from_json_array
    ) or (kind in TRANSPARENT and admitted)
    for name, child in node.items():
        if name not in {"cls", "metadata", "function", "config", "serialization"}:
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


def _probe_values() -> dict[str, object]:
    """Give the probe model values of the exact types its strict fields require."""
    return {
        "aliased": (1,),
        "by_name": {"a": (1,)},
        "nested": ((1,),),
        "unordered": frozenset({1}),
    }
