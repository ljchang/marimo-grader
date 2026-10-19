"""preview_student

Revision ID: c4d8e1f2a903
Revises: b7c2e9d41f03
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op

revision = "c4d8e1f2a903"
down_revision = "b7c2e9d41f03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A staff enrollment switched to see the offering as a student does.
    with op.batch_alter_table("enrollments", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("preview_student", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("enrollments", schema=None) as batch_op:
        batch_op.drop_column("preview_student")
