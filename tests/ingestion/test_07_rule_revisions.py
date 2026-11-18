"""What two committed filings store, recorded under the rule revisions that produced it.

Stored rows carry the names in ``app/ingestion/revisions.py`` instead of a hash of the
code, so nothing notices by itself when a change alters what is stored. This module is
that notice: it parses one SEC and one DART filing from the committed corpus, builds
their chunks and table records, and compares a digest of the result with the digest
recorded here for the running revisions.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import ColumnElement, String

from app.db.models import ParsedStructure, ParsedTable
from app.ingestion.parsing.registry import REGISTRIES
from app.ingestion.pipeline import build_seed_batch, structure_values
from app.ingestion.revisions import BUILDER_REVISION, PARSER_REVISIONS, RESOLVER_REVISION
from app.ingestion.sources.models import Manifest
from app.ingestion.table_records import table_records
from tests.ingestion.support import copy_filing_source

_MANIFEST = Path(__file__).resolve().parents[2] / "data/corpus/manifest.json"
# One SEC and one DART filing, the pair the tutorial indexes.
_SELECTION = "tutorial"


@dataclass(frozen=True, slots=True)
class Stored:
    """The revisions in force for one registry and the digests of what they store."""

    parser: str
    builder: str
    resolver: str
    parsed: str
    tables: str


# Recorded from the committed sources. Change a digest only together with the
# revision of the rule set whose change moved it.
RECORDED = {
    "sec": Stored(
        parser="a70651f3d8d428f4583ac66943fc9ae42ba3786c7c73f8d778448ffce412a2c4",
        builder="b6c8de8881ab7056beedaec1cb5579aa7cf01c0556cce1e97cc224091eff4bc7",
        resolver="83730c4d6e2e0e71da71c4707101e0be181b296760ab1bc0db94a884a504c11e",
        parsed="70ea1930d1864f72c6b971708e61a1f487d2ced0e9b798a594c4623c02ce9ca2",
        tables="083c03d141dcfc9bcc1339b4720e2c28e5719748a4d1982ce322520b28363488",
    ),
    "dart": Stored(
        parser="137a8c01755cfeec2328f7dedaba058c9158ea27abbe06f02b639015b9fd01a5",
        builder="b6c8de8881ab7056beedaec1cb5579aa7cf01c0556cce1e97cc224091eff4bc7",
        resolver="83730c4d6e2e0e71da71c4707101e0be181b296760ab1bc0db94a884a504c11e",
        parsed="d4ff140c07896372adb78d62dbab66fcb38448c2cab2dde924d3aff3df51dc38",
        tables="8d857e1662219c6b6e70d987793e5534a1fc8e8e6619f43b6e7bb04b924ccaab",
    ),
}


def _digest(value: Any) -> str:
    """Hash one JSON-compatible value in a canonical form."""
    payload = json.dumps(
        value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _without(values: dict[str, Any], *names: str) -> dict[str, Any]:
    """Drop the keys that name a revision or derive from one."""
    return {key: value for key, value in values.items() if key not in names}


@pytest.fixture(scope="module")
def measured(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Stored]:
    """Parse, chunk and build the table records of the two filings once."""
    if not _MANIFEST.exists():
        pytest.skip("data/corpus/manifest.json is required for the stored-result record")
    root = tmp_path_factory.mktemp("rule-revisions")
    catalog = Manifest.read(_MANIFEST)
    # Parsing learns profiles next to the sources, so it runs on a copy.
    sources = [
        copy_filing_source(source, root)
        for source in catalog.selected_sources(_SELECTION, _MANIFEST.parent)
    ]
    batch = build_seed_batch(sources)
    structures = {
        filing.source.document.document_id: structure_values(filing) for filing in batch.filings
    }
    facts = {filing.source.document.document_id: filing.facts for filing in batch.filings}
    records = table_records(
        batch.chunks,
        {doc_id: values["structure_id"] for doc_id, values in structures.items()},
        facts,
    )
    out: dict[str, Stored] = {}
    for filing in batch.filings:
        doc_id = filing.source.document.document_id
        registry = filing.source.document.registry
        assert registry not in out, "the selection holds one filing per registry"
        parsed = [
            _without(structures[doc_id], "structure_id", "parser_identity"),
            filing.facts.fingerprint(),
        ]
        tables = [
            [
                # The lexical text is an index transform, not one of the three rule sets.
                _without(chunk.values(), "structure_id", "lexical_text")
                for chunk in batch.chunks
                if chunk.doc_id == doc_id
            ],
            [
                _without(asdict(record), "table_id", "structure_id")
                for record in records
                if record.doc_id == doc_id
            ],
        ]
        out[registry] = Stored(
            parser=PARSER_REVISIONS[registry],
            builder=BUILDER_REVISION,
            resolver=RESOLVER_REVISION,
            parsed=_digest(parsed),
            tables=_digest(tables),
        )
    return out


@pytest.mark.parametrize("registry", sorted(RECORDED))
def test_what_a_filing_stores_changes_only_with_a_revision(
    measured: dict[str, Stored], registry: str
) -> None:
    """A changed stored result under unchanged revisions means a revision must rise."""
    now, recorded = measured[registry], RECORDED[registry]
    same_parser = now.parser == recorded.parser
    same_table_rules = (now.builder, now.resolver) == (recorded.builder, recorded.resolver)

    if same_parser:
        assert now.parsed == recorded.parsed, (
            f"The {registry} parser now finds something else in the same source. "
            f"Give PARSER_REVISIONS[{registry!r}] a new name in app/ingestion/revisions.py, "
            f"then record: {now}"
        )
    if same_parser and same_table_rules:
        assert now.tables == recorded.tables, (
            "The same parse now stores different chunks, cells or readings. Give "
            "BUILDER_REVISION (cells and pieces) or RESOLVER_REVISION (units, currencies, "
            f"years, scopes, items) a new name in app/ingestion/revisions.py, then record: {now}"
        )
    assert now == recorded, f"A revision moved. Record what it stores now: {now}"


def test_every_registry_has_a_parser_revision() -> None:
    """A registry without a named parser revision could not store a structure."""
    assert set(PARSER_REVISIONS) == set(REGISTRIES)


def _width(column: ColumnElement[Any]) -> int:
    """Return the declared length of one string column."""
    assert isinstance(column.type, String) and column.type.length is not None
    return column.type.length


def test_revision_names_fit_the_columns_that_store_them() -> None:
    """A name longer than its column would fail only at the first write."""
    stored = [
        (name, ParsedStructure.__table__.c.parser_identity) for name in PARSER_REVISIONS.values()
    ]
    stored.append((BUILDER_REVISION, ParsedTable.__table__.c.builder_identity))
    stored.append((RESOLVER_REVISION, ParsedTable.__table__.c.resolver_identity))
    for name, column in stored:
        assert name.strip() == name and 0 < len(name) <= _width(column)


def test_revision_names_are_distinct() -> None:
    """Two rule sets sharing a name would make their rows indistinguishable."""
    names = [*PARSER_REVISIONS.values(), BUILDER_REVISION, RESOLVER_REVISION]
    assert len(set(names)) == len(names)
