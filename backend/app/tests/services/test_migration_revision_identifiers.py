"""Every revision identifier must fit the column Alembic stamps it into.

Alembic records the applied revision in ``alembic_version.version_num``, a
``VARCHAR(32)``. A longer identifier is accepted everywhere else — the file
imports, ``alembic heads`` and the whole dependency graph resolve fine — and
only fails on PostgreSQL at the very end of the upgrade, when the stamp is
written:

    StringDataRightTruncation: value too long for type character varying(32)

By then the migration body has already run, so the database carries the data
change while the stamp still names the previous revision. That is the worst
possible moment to find out, which is why this is a static guard rather than
something left to the deployment rehearsal.

Widening the column is not an available fix. Alembic builds the version table
itself through ``DefaultImpl.version_table_impl``, whose only knobs are the
table name, its schema and whether it carries a primary key; the 32 is not
configurable, so ``env.py``'s ``version_table_*`` options cannot reach it. A
hand-rolled ``ALTER TABLE`` would also have to land on every database *before*
an over-long revision could be stamped — and it could not ship as a migration,
because that migration's own stamp is what overflows. The length rule is the
only fix that holds without coordination.

The limit below is read back from the table Alembic will actually create, so
this test tracks the real constraint instead of restating it.
"""

from __future__ import annotations

from pathlib import Path

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

ALEMBIC_ROOT = Path(__file__).resolve().parents[3] / "alembic"


def _version_num_width() -> int:
    """The width of ``alembic_version.version_num`` as Alembic would create it.

    ``_version`` is private, but it is the only handle on the table definition;
    an Alembic release that moves it raises here rather than quietly dropping
    the check.
    """
    context = MigrationContext.configure(dialect_name="postgresql")
    width = context._version.c.version_num.type.length
    assert isinstance(width, int), (
        "Could not read the width of alembic_version.version_num from Alembic; "
        "this guard cannot be trusted until it is repointed at the real column."
    )
    return width


def test_no_revision_identifier_exceeds_the_version_table_column() -> None:
    width = _version_num_width()
    revisions = list(ScriptDirectory(str(ALEMBIC_ROOT)).walk_revisions())
    assert revisions, f"No revisions found under {ALEMBIC_ROOT}; the guard would pass vacuously."

    too_long = {
        script.revision: len(script.revision)
        for script in revisions
        if len(script.revision) > width
    }
    assert not too_long, (
        f"Revision identifiers longer than the {width} characters "
        f"alembic_version.version_num holds: {too_long}. Shorten the identifier — "
        "the filename may stay long and descriptive, only the identifier is capped."
    )
