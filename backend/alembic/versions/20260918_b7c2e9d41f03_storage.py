"""storage: groups, group members, storage grants

Revision ID: b7c2e9d41f03
Revises: a1b2c3d4e5f6
Create Date: 2026-09-18
"""

import sqlalchemy as sa
from alembic import op

revision = "b7c2e9d41f03"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("offering_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["offering_id"], ["offerings.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("offering_id", "slug", name="uq_group_slug"),
    )
    op.create_index("ix_groups_offering_id", "groups", ["offering_id"])
    op.create_table(
        "group_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "enrollment_id", name="uq_group_member"),
    )
    op.create_index("ix_group_members_group_id", "group_members", ["group_id"])
    op.create_index("ix_group_members_enrollment_id", "group_members", ["enrollment_id"])
    # Append-only: who was handed which prefixes, and for how long.
    op.create_table(
        "storage_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("offering_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("prefixes_ro", sa.JSON(), nullable=False),
        sa.Column("prefixes_rw", sa.JSON(), nullable=False),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("client", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["offering_id"], ["offerings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_storage_grants_offering_id", "storage_grants", ["offering_id"])
    op.create_index("ix_storage_grants_user_id", "storage_grants", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_storage_grants_user_id", table_name="storage_grants")
    op.drop_index("ix_storage_grants_offering_id", table_name="storage_grants")
    op.drop_table("storage_grants")
    op.drop_index("ix_group_members_enrollment_id", table_name="group_members")
    op.drop_index("ix_group_members_group_id", table_name="group_members")
    op.drop_table("group_members")
    op.drop_index("ix_groups_offering_id", table_name="groups")
    op.drop_table("groups")
