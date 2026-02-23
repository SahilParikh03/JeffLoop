"""Create users table and add FK constraints to signals + user_profiles

Revision ID: 006_users_table
Revises: 005_discord_profile
Create Date: 2026-02-23

Adds:
  - users table (id, email, created_at, is_active)
  - FK: signals.tenant_id -> users.id  (enforces REFERENCES users(id) per spec Section 14)
  - FK: user_profiles.id  -> users.id  (1:1 extension table pattern)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "006_users_table"
down_revision: Union[str, None] = "005_discord_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create users table
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.BOOLEAN(),
            server_default="true",
            nullable=False,
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ------------------------------------------------------------------
    # 2. FK: signals.tenant_id -> users.id
    #    Enforces spec Section 14 "REFERENCES users(id)".
    # ------------------------------------------------------------------
    op.create_foreign_key(
        "fk_signals_tenant_id_users",
        "signals",
        "users",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ------------------------------------------------------------------
    # 3. FK: user_profiles.id -> users.id (1:1 extension)
    #    A user_profile row is always backed by a users row with the same PK.
    # ------------------------------------------------------------------
    op.create_foreign_key(
        "fk_user_profiles_id_users",
        "user_profiles",
        "users",
        ["id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_user_profiles_id_users", "user_profiles", type_="foreignkey")
    op.drop_constraint("fk_signals_tenant_id_users", "signals", type_="foreignkey")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
