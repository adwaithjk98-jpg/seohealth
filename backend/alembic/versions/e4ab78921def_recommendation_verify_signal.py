"""recommendation.verify_signal

A stable key (e.g. ``website.has_meta_description``) that lets the
fix-loop verifier check whether the underlying raw_data signal has
turned positive on a subsequent audit. NULL for recs the scrapers
haven't tagged (NAP cross-source findings, anything ambiguous) — those
stay outside the auto-verification flow and the user marks them
done/dismissed manually.

Revision ID: e4ab78921def
Revises: d2f9c47b5103
Create Date: 2026-05-27
"""

from alembic import op
import sqlalchemy as sa


revision = "e4ab78921def"
down_revision = "d2f9c47b5103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.add_column(sa.Column("verify_signal", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.drop_column("verify_signal")
