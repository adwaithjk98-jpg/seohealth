"""competitor_observations.audit_id nullable

Phase 4 -> 4.x architectural shift: competitor observations stop being
piggybacks on user-triggered audits. The weekly ``competitor_refresh``
cron now writes observation rows directly (audit_id IS NULL), keeping
competitor trend lines alive in weeks the user doesn't run an audit.
Legacy rows from the in-audit path keep their real audit_id; nothing
backfills.

Revision ID: a3c5d917b2e6
Revises: 8b6c4e2f1a9d
Create Date: 2026-05-26
"""

from alembic import op
import sqlalchemy as sa


revision = "a3c5d917b2e6"
down_revision = "8b6c4e2f1a9d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite needs the batch context to alter a column's nullability;
    # Postgres handles ``alter_column`` directly. ``batch_alter_table``
    # works on both via the SQLAlchemy abstraction so we don't need a
    # dialect-switched code path here.
    with op.batch_alter_table("competitor_observations") as batch_op:
        batch_op.alter_column("audit_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # Best-effort downgrade. If cron-written rows exist (audit_id IS NULL),
    # this will fail at the NOT NULL re-add — caller would need to delete
    # them first. Acceptable for a one-way migration like this.
    with op.batch_alter_table("competitor_observations") as batch_op:
        batch_op.alter_column("audit_id", existing_type=sa.Integer(), nullable=False)
