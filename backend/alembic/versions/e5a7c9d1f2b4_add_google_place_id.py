"""add google_place_id to businesses + competitors

Stores the resolved Places API (New) place id for a Maps listing. Nullable and
lazily backfilled (null-only) by the Maps audit / competitor refresh so
recurring reads hit a cheap Place Details call and stay pinned to the exact
listing. Part of the maps.py Selenium → Places API migration.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e5a7c9d1f2b4"
down_revision = "d8e3f1a64c20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "businesses",
        sa.Column("google_place_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "competitors",
        sa.Column("google_place_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("competitors", "google_place_id")
    op.drop_column("businesses", "google_place_id")
