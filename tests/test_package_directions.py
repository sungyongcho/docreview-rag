"""Packages under ``app`` import each other in one direction.

A package is a directory or a module directly under ``app``. Every import counts,
including one deferred into a function or guarded by ``TYPE_CHECKING``: a deferred
import that closes a cycle still means two packages cannot be understood, tested or
moved without each other.
"""

import ast
from collections import defaultdict
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

type Imports = dict[tuple[str, str], list[str]]


def _package_imports(root: Path) -> Imports:
    """Map each (importing package, imported package) pair to the import sites."""
    found: Imports = defaultdict(list)
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        source = relative.parts[0] if len(relative.parts) > 1 else relative.stem
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            for module in modules:
                parts = module.split(".")
                if parts[0] == "app" and len(parts) > 1 and parts[1] != source:
                    found[(source, parts[1])].append(f"{relative}:{node.lineno} imports {module}")
    return found


def _cycles(pairs: set[tuple[str, str]]) -> list[list[str]]:
    """Return every group of packages that reach each other, by Tarjan's algorithm."""
    graph: dict[str, set[str]] = defaultdict(set)
    for source, target in pairs:
        graph[source].add(target)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    groups: list[list[str]] = []

    def visit(package: str) -> None:
        """Number one package and close the group it roots."""
        index[package] = low[package] = len(index)
        stack.append(package)
        for target in sorted(graph.get(package, ())):
            if target not in index:
                visit(target)
                low[package] = min(low[package], low[target])
            elif target in stack:
                low[package] = min(low[package], index[target])
        if low[package] == index[package]:
            group = [stack.pop()]
            while group[-1] != package:
                group.append(stack.pop())
            if len(group) > 1:
                groups.append(sorted(group))

    for package in sorted(graph):
        if package not in index:
            visit(package)
    return sorted(groups)


def test_the_cycle_finder_reports_each_group_that_imports_in_a_circle() -> None:
    """Find a two-package and a three-package circle and leave a straight chain alone."""
    pairs = {("a", "b"), ("b", "a"), ("c", "d"), ("d", "e"), ("e", "c"), ("x", "y"), ("y", "a")}

    assert _cycles(pairs) == [["a", "b"], ["c", "d", "e"]]
    assert _cycles({("x", "y"), ("y", "z")}) == []


def test_app_packages_import_each_other_in_one_direction() -> None:
    """Fail with the import sites inside every circle of packages."""
    imports = _package_imports(APP)
    assert imports, "no imports between app packages were found; the scan is broken"

    report = [
        f"{source} -> {target}: " + "; ".join(sites)
        for group in _cycles(set(imports))
        for (source, target), sites in sorted(imports.items())
        if source in group and target in group
    ]

    assert not report, (
        "Packages under app import each other in a circle. Move the shared symbol to the "
        "package both sides depend on, or let the lower package publish an event the "
        "higher one subscribes to:\n" + "\n".join(report)
    )
