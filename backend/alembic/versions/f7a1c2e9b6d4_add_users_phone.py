"""add users.phone

Optional contact number collected at signup — the pre-beta foundation for S1
(WhatsApp-first weekly recaps). One nullable column; NULL for every existing
user, so the add is non-destructive and needs no default. The WhatsApp send
pipeline itself is a post-beta build; this just makes sure the channel has a
number on file when that day comes.

Revision ID: f7a1c2e9b6d4
Revises: e5a7c9d1f2b4
Create Date: 2026-07-24
"""

import sqlalchemy as sa
from alembic import op


revision = "f7a1c2e9b6d4"
down_revision = "e5a7c9d1f2b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("phone", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("phone")
