"""Add account, household, property, appliance, and service-history tables.

Revision ID: 0002_identity_inventory
Revises: 0001_enable_pgvector
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_identity_inventory"
down_revision: str | None = "0001_enable_pgvector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

uuid_type = sa.Uuid(as_uuid=True)
created_at = sa.DateTime(timezone=True)


def upgrade() -> None:
    """Create the initial identity and inventory relational schema."""
    op.create_table(
        "users",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", created_at, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "households",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("created_at", created_at, server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "household_memberships",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "household_id",
            uuid_type,
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            uuid_type,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", created_at, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'member')", name="ck_membership_role"),
        sa.UniqueConstraint("household_id", "user_id", name="uq_membership_household_user"),
    )
    op.create_index("ix_membership_user_active", "household_memberships", ["user_id", "is_active"])

    op.create_table(
        "properties",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "household_id",
            uuid_type,
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("address_line", sa.String(length=240)),
        sa.Column("city", sa.String(length=120)),
        sa.Column("region", sa.String(length=120)),
        sa.Column("postal_code", sa.String(length=32)),
        sa.Column("country", sa.String(length=2)),
        sa.Column("archived_at", created_at),
        sa.Column("created_at", created_at, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", created_at, server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_properties_household_archived", "properties", ["household_id", "archived_at"]
    )

    op.create_table(
        "technicians",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "household_id",
            uuid_type,
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("phone", sa.String(length=40)),
        sa.Column("email", sa.String(length=320)),
        sa.Column("organization", sa.String(length=160)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", created_at, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", created_at, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_technicians_household_active", "technicians", ["household_id", "is_active"])

    op.create_table(
        "appliances",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "property_id",
            uuid_type,
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("make", sa.String(length=120)),
        sa.Column("model", sa.String(length=120)),
        sa.Column("serial_number", sa.String(length=160)),
        sa.Column("purchase_date", sa.Date()),
        sa.Column("warranty_expiry", sa.Date()),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", created_at, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", created_at, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_appliance_status"),
    )
    op.create_index("ix_appliances_property_status", "appliances", ["property_id", "status"])

    op.create_table(
        "qr_tags",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "appliance_id",
            uuid_type,
            sa.ForeignKey("appliances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tag_id", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("public_fields", sa.JSON(), nullable=False),
        sa.Column("revoked_at", created_at),
        sa.Column("created_at", created_at, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_qr_tags_tag_id", "qr_tags", ["tag_id"], unique=True)
    op.create_index("ix_qr_tags_appliance_active", "qr_tags", ["appliance_id", "is_active"])

    op.create_table(
        "appliance_technicians",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "appliance_id",
            uuid_type,
            sa.ForeignKey("appliances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "technician_id",
            uuid_type,
            sa.ForeignKey("technicians.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("appliance_id", "technician_id"),
    )

    op.create_table(
        "service_records",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "appliance_id",
            uuid_type,
            sa.ForeignKey("appliances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "technician_id",
            uuid_type,
            sa.ForeignKey("technicians.id", ondelete="SET NULL"),
        ),
        sa.Column("serviced_at", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("cost", sa.Numeric(10, 2)),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("created_at", created_at, server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_service_records_appliance_date",
        "service_records",
        ["appliance_id", "serviced_at"],
    )


def downgrade() -> None:
    """Drop the Phase 3 domain tables in dependency order."""
    op.drop_index("ix_service_records_appliance_date", table_name="service_records")
    op.drop_table("service_records")
    op.drop_table("appliance_technicians")
    op.drop_index("ix_qr_tags_appliance_active", table_name="qr_tags")
    op.drop_index("ix_qr_tags_tag_id", table_name="qr_tags")
    op.drop_table("qr_tags")
    op.drop_index("ix_appliances_property_status", table_name="appliances")
    op.drop_table("appliances")
    op.drop_index("ix_technicians_household_active", table_name="technicians")
    op.drop_table("technicians")
    op.drop_index("ix_properties_household_archived", table_name="properties")
    op.drop_table("properties")
    op.drop_index("ix_membership_user_active", table_name="household_memberships")
    op.drop_table("household_memberships")
    op.drop_table("households")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
