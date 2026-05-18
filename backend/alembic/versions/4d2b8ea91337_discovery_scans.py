"""discovery_scans table

Phase 4 §3: Discovery Scan request log + rate-limit ledger. One row per
user-initiated heavy bulk scrape; monthly per-user cap is enforced by
counting rows in the current calendar month.

Revision ID: 4d2b8ea91337
Revises: 9c1ae27f4d0c
Create Date: 2026-05-18 13:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4d2b8ea91337'
down_revision: Union[str, None] = '9c1ae27f4d0c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'discovery_scans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('business_id', sa.Integer(), nullable=True),
        sa.Column('query', sa.String(length=512), nullable=False),
        sa.Column('num_leads', sa.Integer(), nullable=False),
        sa.Column('fields_csv', sa.String(length=1024), nullable=False),
        sa.Column('filters', sa.String(length=1024), nullable=True),
        sa.Column(
            'status',
            sa.Enum('pending', 'running', 'done', 'failed', name='discovery_scan_status'),
            nullable=False,
        ),
        sa.Column(
            'requested_at',
            sa.DateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('result_count', sa.Integer(), nullable=True),
        sa.Column('results_json', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.String(length=1024), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('discovery_scans', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_discovery_scans_user_id'),
            ['user_id'],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('discovery_scans', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_discovery_scans_user_id'))
    op.drop_table('discovery_scans')
