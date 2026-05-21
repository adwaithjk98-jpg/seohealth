"""competitor_observations: instagram_followers + instagram_posts

Phase 4.6 — wire Instagram metrics so the Market matrix and Deep Dive
trend chart can offer them as toggle options. Both columns are nullable
since the existing rows have no IG data, and the scraper still needs to
be updated to actually populate them.

Revision ID: 8b6c4e2f1a9d
Revises: 7e1f3a82d4cb
Create Date: 2026-05-21 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8b6c4e2f1a9d'
down_revision: Union[str, None] = '7e1f3a82d4cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('competitor_observations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('instagram_followers', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('instagram_posts', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('competitor_observations', schema=None) as batch_op:
        batch_op.drop_column('instagram_posts')
        batch_op.drop_column('instagram_followers')
