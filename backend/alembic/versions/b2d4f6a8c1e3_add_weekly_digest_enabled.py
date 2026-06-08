"""add users.weekly_digest_enabled

Opt-out flag for the weekly digest email. Defaults to true so existing users
keep their current (implicit) behavior; the account page + the email's
unsubscribe link flip it, and the digest dispatcher filters on it.

``server_default=text("true")`` works on both SQLite (TRUE -> 1 since 3.23) and
PostgreSQL, so no dialect branching needed here.

Revision ID: b2d4f6a8c1e3
Revises: a1c3f5b7d9e2
Create Date: 2026-06-08
"""

import sqlalchemy as sa
from alembic import op


revision = "b2d4f6a8c1e3"
down_revision = "a1c3f5b7d9e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "weekly_digest_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("weekly_digest_enabled")
