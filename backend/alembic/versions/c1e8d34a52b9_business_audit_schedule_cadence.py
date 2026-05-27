"""business.audit_schedule_cadence

Per-business auto-audit cadence (opt-in as of 2026-05-26). NULL means
no schedule; non-null is a short string like ``'weekly'`` / ``'biweekly'``
/ ``'monthly'``.

Revision ID: c1e8d34a52b9
Revises: a3c5d917b2e6
Create Date: 2026-05-26
"""

from alembic import op
import sqlalchemy as sa


revision = "c1e8d34a52b9"
down_revision = "a3c5d917b2e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.add_column(
            sa.Column("audit_schedule_cadence", sa.String(length=16), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.drop_column("audit_schedule_cadence")
