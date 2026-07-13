"""Add 'performance' value to the audit_section_name enum.

The Performance / Site-Speed pillar (Core Web Vitals via the PageSpeed
Insights API) persists its results as an ``audit_sections`` row like every
other pillar, so the native Postgres enum needs the new label before any
audit can write it.

Postgres: on PG 12+ (prod is PG 16) ``ALTER TYPE ... ADD VALUE`` runs fine
inside Alembic's transaction — the only restriction is that the new value
can't be *used* in that same transaction, and we don't (no rows are written
here). ``IF NOT EXISTS`` makes it idempotent / re-runnable. Earlier revisions
of this migration tried to flip the connection to autocommit or open a second
connection; both fail — psycopg2 forbids autocommit mid-transaction, and a
separate connection can't see the enum type created earlier in this same
still-uncommitted Alembic transaction. (Verified by scripts/check_migrations.sh
against Postgres 16.)

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

    # PG 12+ allows this inside Alembic's transaction; we never use the value
    # in this migration, so the same-transaction restriction doesn't apply.
    op.execute("ALTER TYPE audit_section_name ADD VALUE IF NOT EXISTS 'performance'")


def downgrade() -> None:
    # No-op: Postgres can't drop an enum value, and rows may reference it.
    pass
