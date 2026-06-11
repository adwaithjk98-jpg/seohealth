"""add push_subscriptions table

Web Push (VAPID) device subscriptions. One row per browser PushSubscription;
the presence of any row for a user is the "push enabled" state. ``endpoint`` is
unique so a device re-subscribe upserts in place. FK cascades on user delete so
account deletion drops a user's subscriptions with the rest of their data.

The UNIQUE on ``endpoint`` is declared inline in CREATE TABLE (not a follow-up
ALTER) so this runs on SQLite dev as well as Postgres prod without batch mode.

Revision ID: f3b9d6c2a4e7
Revises: b2d4f6a8c1e3
Create Date: 2026-06-11
"""

import sqlalchemy as sa
from alembic import op


revision = "f3b9d6c2a4e7"
down_revision = "b2d4f6a8c1e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.String(length=512), nullable=False, unique=True),
        sa.Column("p256dh", sa.String(length=255), nullable=False),
        sa.Column("auth", sa.String(length=255), nullable=False),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
