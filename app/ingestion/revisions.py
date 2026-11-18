"""Name the revisions of the rules whose output is stored for a filing.

Three rule sets decide what the database holds for one source file: the parser
(sections, tables and tagged facts), the table builder (normalized cells and the
pieces each chunk carries) and the reader (units, currencies, years, scopes and
items). Every stored structure and table carries the revision that produced it, and
a stored table whose revisions differ from the running ones is not used as evidence.

A revision is a name, not a measurement of the code. Editing a comment, a docstring
or the shape of the code leaves stored rows current. Raise a revision in the same
commit as a change that alters what is stored for the same source, and re-index the
database afterwards. ``tests/ingestion/test_07_rule_revisions.py`` records what two
committed filings store under the running revisions and fails when that result
changes while the revisions stay.

The first revision of each rule set is named by the value the rows stored before
revisions existed already carry, so those rows stay current. Name later revisions
``<rule set>-<number>``, for example ``builder-2`` or ``parser-sec-2``.
"""

from typing import Final

# The parser of each registry: ``app/ingestion/parsing``. Its revision is part of a
# parsed structure's identity, so raising it stores every filing of that registry as
# a new structure with new tables.
PARSER_REVISIONS: Final[dict[str, str]] = {
    "sec": "a70651f3d8d428f4583ac66943fc9ae42ba3786c7c73f8d778448ffce412a2c4",
    "dart": "137a8c01755cfeec2328f7dedaba058c9158ea27abbe06f02b639015b9fd01a5",
}

# The rules that turn a parsed table into normalized cells and chunk pieces:
# ``app/ingestion/parsing/tables.py``, ``app/ingestion/chunking.py`` and
# ``app/ingestion/table_records.py``.
BUILDER_REVISION: Final = "b6c8de8881ab7056beedaec1cb5579aa7cf01c0556cce1e97cc224091eff4bc7"

# The rules that read units, currencies, years, scopes and items from a table:
# ``app/figures`` and the fact reader ``app/ingestion/parsing/facts.py``.
RESOLVER_REVISION: Final = "83730c4d6e2e0e71da71c4707101e0be181b296760ab1bc0db94a884a504c11e"
