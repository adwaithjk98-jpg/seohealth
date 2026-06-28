"""Add 'performance' value to the audit_section_name enum.

The Performance / Site-Speed pillar (Core Web Vitals via the PageSpeed
Insights API) persists its results as an ``audit_sections`` row like every
other pillar, so the native Postgres enum needs the new label before any
audit can write it.

Postgres: ``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction
block on older servers, and even on PG 12+ the freshly-added value can't be
used in the same transaction. Alembic wraps each migration in a transaction,
so we grab the raw DBAPI connection and issue the ALTER with autocommit.
``IF NOT EXISTS`` makes the migration idempotent / re-runnable.

SQLite: SQLAlchemy 2.0 renders ``Enum`` without a CHECK constraint by
default (``create_constraint=False``), so the column is plain VARCHAR and
the new value just works — this migration is a no-op there.

Downgrade is intentionally a no-op: Postgres has no ``ALTER TYPE ... DROP
VALUE``, and removing an enum label that rows may reference is unsafe. The
extra label is harmless if left in place on a rollback.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "c7f2a91b3e84"
down_revision = "f3b9d6c2a4e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite (and anything non-PG) stores the enum as VARCHAR with no
        # CHECK constraint, so there's nothing to migrate.
        return

    # ALTER TYPE ... ADD VALUE must run outside a transaction. Use the raw
    # psycopg connection in autocommit so it isn't swept into Alembic's txn.
    raw = bind.connection.connection  # DBAPI connection
    old_autocommit = raw.autocommit
    raw.autocommit = True
    try:
        with raw.cursor() as cur:
            cur.execute(
                "ALTER TYPE audit_section_name ADD VALUE IF NOT EXISTS 'performance'"
            )
    finally:
        raw.autocommit = old_autocommit


def downgrade() -> None:
    # No-op: Postgres can't drop an enum value, and rows may reference it.
    pass
