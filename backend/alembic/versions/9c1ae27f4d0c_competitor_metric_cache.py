"""competitor_metric_cache table

Phase 4 cost defense: global cross-user cache of Google Maps metrics
(rating + review_count) keyed by normalized maps_url. Lets two users
tracking the same place share one scrape result for 7 days.

Revision ID: 9c1ae27f4d0c
Revises: 3a4c1b9d2e58
Create Date: 2026-05-18 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9c1ae27f4d0c'
down_revision: Union[str, None] = '3a4c1b9d2e58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'competitor_metric_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cache_key', sa.String(length=1024), nullable=False),
        sa.Column('maps_url', sa.String(length=1024), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('rating', sa.Float(), nullable=True),
        sa.Column('review_count', sa.Integer(), nullable=True),
        sa.Column(
            'last_scraped_at',
            sa.DateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column('last_error', sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('competitor_metric_cache', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_competitor_metric_cache_cache_key'),
            ['cache_key'],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table('competitor_metric_cache', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_competitor_metric_cache_cache_key'))
    op.drop_table('competitor_metric_cache')
