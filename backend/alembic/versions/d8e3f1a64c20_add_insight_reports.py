"""add insight_reports table

Stores user-submitted "this insight looks wrong" reports. Recommendation FK
is SET NULL on delete (recs cascade-delete with their audit when pruned), and
the rec's identifying fields are denormalized so a report stays readable after
the underlying recommendation is gone.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d8e3f1a64c20"
down_revision = "c7f2a91b3e84"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "insight_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=True),
        sa.Column("audit_id", sa.Integer(), nullable=True),
        sa.Column("recommendation_id", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(length=32), nullable=True),
        sa.Column("rec_title", sa.String(length=512), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "resolved",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["recommendation_id"], ["recommendations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_insight_reports_user_id"),
        "insight_reports",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_insight_reports_user_id"), table_name="insight_reports")
    op.drop_table("insight_reports")
