"""Add subscription_tier column to user_profiles

Revision ID: 007_subscription_tier
Revises: 006_users_table
Create Date: 2026-02-23

Adds:
  - user_profiles.subscription_tier (String, server_default='free')
    Values: free | trader | pro | shop  (spec Section 10)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "007_subscription_tier"
down_revision: Union[str, None] = "006_users_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column(
            "subscription_tier",
            sa.String(),
            server_default="free",
            nullable=False,
            comment="Subscription tier: free | trader | pro | shop",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "subscription_tier")
