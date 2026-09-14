"""preferred_name

Revision ID: a1b2c3d4e5f6
Revises: 71f30487b560
Create Date: 2026-09-14
"""

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "71f30487b560"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Separate from display_name, which SAML overwrites on every login.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("preferred_name", sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("preferred_name")
