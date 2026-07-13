"""FTUE questionnaire: user.display_name, business.business_type/has_website/
has_instagram, recommendation.fix_target.

Adds the column set that powers the first-time-user questionnaire so the
app can be tailored to each business's actual shape (website-less cafés,
B2B suppliers, etc.) instead of penalising channels the user genuinely
doesn't use.

* ``users.display_name`` — friendly greeting label, free-text, NULL until set.
* ``businesses.business_type`` — short tag for cascading copy & weighting.
  Allowed values are application-defined; DB just stores a string.
* ``businesses.has_website`` — opt-out toggle. NULL = never asked,
  True = has one (compare against ``website`` URL),
  False = explicitly doesn't, hide the Website pillar.
* ``businesses.has_instagram`` — symmetric to ``has_website``.
* ``recommendations.fix_target`` — which pillar the user would actually
  *act on* to fix this finding (usually equals ``section`` but differs
  for cross-pillar NAP findings). Lets the read path filter recs whose
  target is an opted-out pillar.

Revision ID: d2f9c47b5103
Revises: c1e8d34a52b9
Create Date: 2026-05-27
"""

from alembic import op
import sqlalchemy as sa


revision = "d2f9c47b5103"
down_revision = "c1e8d34a52b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("display_name", sa.String(length=255), nullable=True))

    with op.batch_alter_table("businesses") as batch_op:
        batch_op.add_column(sa.Column("business_type", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("has_website", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("has_instagram", sa.Boolean(), nullable=True))

    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.add_column(sa.Column("fix_target", sa.String(length=32), nullable=True))

    # Backfill: any business that already has a website URL is implicitly
    # ``has_website=True``; any with an IG handle is ``has_instagram=True``.
    # Unknown stays NULL so the dashboard can prompt only for genuinely
    # un-asked businesses.
    # Use the ``true`` keyword, not ``1`` — SQLite (dev) is typeless and accepts
    # either, but Postgres (prod) rejects an integer literal for a boolean column
    # ("column is of type boolean but expression is of type integer"). Caught by
    # scripts/check_migrations.sh before it could break the first prod deploy.
    op.execute("UPDATE businesses SET has_website = true WHERE website IS NOT NULL AND website != ''")
    op.execute("UPDATE businesses SET has_instagram = true WHERE ig_handle IS NOT NULL AND ig_handle != ''")


def downgrade() -> None:
    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.drop_column("fix_target")
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.drop_column("has_instagram")
        batch_op.drop_column("has_website")
        batch_op.drop_column("business_type")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("display_name")
