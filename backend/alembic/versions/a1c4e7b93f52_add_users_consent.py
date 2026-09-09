"""add users.consent_at + users.consent_version

DPDP Act 2023 asks for consent that is informed and given by a clear
affirmative action, and for the fiduciary to be able to show it was given.
The published privacy policy states we process on the basis of the consent
given at account creation, so that consent needs a record behind it.

Two nullable columns, set once when the account is first created (see
``services/auth.issue_magic_link``). NULL for every pre-existing user — they
signed up before the checkbox existed and we do not claim otherwise. The
version string pins *which* policy text was agreed to, so a later rewrite
doesn't silently rewrite history.

Revision ID: a1c4e7b93f52
Revises: f7a1c2e9b6d4
Create Date: 2026-08-29
"""

import sqlalchemy as sa
from alembic import op


revision = "a1c4e7b93f52"
down_revision = "f7a1c2e9b6d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("consent_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("consent_version", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("consent_version")
        batch_op.drop_column("consent_at")
