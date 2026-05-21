"""competitors: instagram_url + website_url

Phase 4 manual-add flow: users can paste IG and website URLs alongside
the Maps URL when adding a competitor by hand. Both are nullable — the
audit-side scraper still discovers them from the Maps listing when
omitted, so the columns are pure pre-seeded hints.

Revision ID: 7e1f3a82d4cb
Revises: 4d2b8ea91337
Create Date: 2026-05-20 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7e1f3a82d4cb'
down_revision: Union[str, None] = '4d2b8ea91337'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('competitors', schema=None) as batch_op:
        batch_op.add_column(sa.Column('instagram_url', sa.String(length=1024), nullable=True))
        batch_op.add_column(sa.Column('website_url', sa.String(length=1024), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('competitors', schema=None) as batch_op:
        batch_op.drop_column('website_url')
        batch_op.drop_column('instagram_url')
