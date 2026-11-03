"""submission_snapshot

Revision ID: d9e4a7b3c512
Revises: c4d8e1f2a903
Create Date: 2026-11-03
"""

import sqlalchemy as sa
from alembic import op

revision = "d9e4a7b3c512"
down_revision = "c4d8e1f2a903"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # marimo's session snapshot sent with an attempt: the student's own outputs.
    with op.batch_alter_table("submissions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("snapshot_artifact_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_submissions_snapshot_artifact", "artifacts", ["snapshot_artifact_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("submissions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_submissions_snapshot_artifact", type_="foreignkey")
        batch_op.drop_column("snapshot_artifact_id")
