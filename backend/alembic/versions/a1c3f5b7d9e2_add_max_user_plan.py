"""add 'max' value to user_plan enum

Introduces the Max (multi-location / agency) tier. On PostgreSQL the
``user_plan`` type is a native ENUM, so the new value has to be added with
``ALTER TYPE``. On SQLite the column is a plain VARCHAR with no CHECK
constraint, so there's nothing to migrate — the new value just works.

Revision ID: a1c3f5b7d9e2
Revises: e4ab78921def
Create Date: 2026-06-06
"""

from alembic import op


revision = "a1c3f5b7d9e2"
down_revision = "e4ab78921def"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # IF NOT EXISTS keeps the migration idempotent. ADD VALUE runs inside
        # the migration transaction fine on PostgreSQL 12+ (production target).
        op.execute("ALTER TYPE user_plan ADD VALUE IF NOT EXISTS 'max'")
    # SQLite: no-op. The column is VARCHAR with no enum constraint.


def downgrade() -> None:
    # PostgreSQL cannot drop a value from an enum type without recreating it,
    # and no row should reference 'max' if we're rolling the feature back.
    # Leaving the (now-unused) value in place is the safe, conventional choice.
    pass
