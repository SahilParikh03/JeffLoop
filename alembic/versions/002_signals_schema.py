"""Add signals + signal_audit tables with RLS policies

Revision ID: 002_signals_schema
Revises: 001_initial_schema
Create Date: 2026-02-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers
revision: str = "002_signals_schema"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- signals table (tenant-isolated via RLS) ---
    op.create_table(
        "signals",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("card_id", sa.String(), nullable=False),
        sa.Column("card_name", sa.String(), nullable=False),
        sa.Column("signal_type", sa.String(), nullable=False, server_default="arbitrage"),
        sa.Column("price_eur", sa.DECIMAL(10, 2), nullable=False),
        sa.Column("price_usd", sa.DECIMAL(10, 2), nullable=False),
        sa.Column("net_profit", sa.DECIMAL(10, 2), nullable=False),
        sa.Column("margin_pct", sa.DECIMAL(6, 2), nullable=False),
        sa.Column("velocity_score", sa.DECIMAL(6, 2), nullable=True),
        sa.Column("velocity_tier", sa.INTEGER(), nullable=True),
        sa.Column("headache_score", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("headache_tier", sa.INTEGER(), nullable=True),
        sa.Column("maturity_multiplier", sa.DECIMAL(3, 2), nullable=True),
        sa.Column("condition", sa.String(), nullable=True),
        sa.Column("regulation_mark", sa.String(), nullable=True),
        sa.Column("rotation_risk", sa.String(), nullable=True),
        sa.Column("trend_classification", sa.String(), nullable=True),
        sa.Column("bundle_tier", sa.String(), nullable=True),
        sa.Column("tcgplayer_url", sa.String(), nullable=True),
        sa.Column("cardmarket_url", sa.String(), nullable=True),
        sa.Column("cascade_count", sa.INTEGER(), nullable=False, server_default="0"),
        sa.Column("acted_on", sa.BOOLEAN(), nullable=False, server_default="false"),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_signals_tenant_id", "signals", ["tenant_id"])
    op.create_index("ix_signals_tenant_created", "signals", ["tenant_id", "created_at"])

    # --- signal_audit table (admin-only, append-only, NO RLS) ---
    op.create_table(
        "signal_audit",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("signal_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_prices", JSONB(), nullable=False),
        sa.Column("fee_calc", JSONB(), nullable=False),
        sa.Column("snapshot_data", JSONB(), nullable=False),
        sa.Column("calculation_version", sa.String(), nullable=False, server_default="v1"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_signal_audit_signal_id", "signal_audit", ["signal_id"])

    # FK constraint: signal_audit.signal_id -> signals.id
    op.create_foreign_key(
        "fk_signal_audit_signal_id",
        "signal_audit",
        "signals",
        ["signal_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # -----------------------------------------------------------------------
    # RLS Policies on signals table
    #
    # Uses PostgreSQL session variable `app.tenant_id` set by the application
    # on each connection. The app role connects with limited privileges;
    # superuser bypasses RLS for admin/migration operations.
    #
    # SECURITY: signal_audit has NO RLS -- admin-only, append-only.
    # -----------------------------------------------------------------------

    # Enable RLS on signals
    op.execute("ALTER TABLE signals ENABLE ROW LEVEL SECURITY")

    # Force RLS even for table owners (defense in depth)
    op.execute("ALTER TABLE signals FORCE ROW LEVEL SECURITY")

    # SELECT policy: users can only read their own signals
    op.execute("""
        CREATE POLICY tenant_isolation ON signals
            FOR SELECT
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    """)

    # INSERT policy: users can only insert signals for themselves
    op.execute("""
        CREATE POLICY tenant_insert ON signals
            FOR INSERT
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
    """)

    # UPDATE policy: users can only update their own signals (e.g., acted_on flag)
    op.execute("""
        CREATE POLICY tenant_update ON signals
            FOR UPDATE
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
    """)


def downgrade() -> None:
    # Drop RLS policies before dropping the table
    op.execute("DROP POLICY IF EXISTS tenant_update ON signals")
    op.execute("DROP POLICY IF EXISTS tenant_insert ON signals")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON signals")
    op.execute("ALTER TABLE signals DISABLE ROW LEVEL SECURITY")

    # Drop FK constraint
    op.execute("ALTER TABLE signal_audit DROP CONSTRAINT IF EXISTS fk_signal_audit_signal_id")

    # Drop tables
    op.drop_index("ix_signal_audit_signal_id", table_name="signal_audit")
    op.drop_table("signal_audit")
    op.drop_index("ix_signals_tenant_created", table_name="signals")
    op.drop_index("ix_signals_tenant_id", table_name="signals")
    op.drop_table("signals")
