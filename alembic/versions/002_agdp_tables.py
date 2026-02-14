"""Add aGDP leaderboard tables

Revision ID: 002
Revises: 001
Create Date: 2026-02-14

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agdp_epochs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('epoch_number', sa.Integer(), nullable=True),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=True),
        sa.Column('usdc_snapshot', sa.Float(), server_default='0'),
        sa.Column('cbbtc_snapshot', sa.Float(), server_default='0'),
        sa.Column('prize_pool_total', sa.Float(), nullable=True),
        sa.Column('prize_pool_usdc', sa.Float(), nullable=True),
        sa.Column('prize_pool_cbbtc_balance', sa.Float(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_agdp_epochs_epoch_number', 'agdp_epochs', ['epoch_number'], unique=True)

    op.create_table(
        'agdp_agents',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('agent_id', sa.Integer(), nullable=True),
        sa.Column('epoch_id', sa.Integer(), nullable=True),
        sa.Column('agent_name', sa.String(200), nullable=True),
        sa.Column('agent_wallet_address', sa.String(42), nullable=True),
        sa.Column('token_address', sa.String(42), nullable=True),
        sa.Column('profile_pic', sa.Text(), nullable=True),
        sa.Column('tag', sa.String(100), nullable=True),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('role', sa.String(50), nullable=True),
        sa.Column('symbol', sa.String(20), nullable=True),
        sa.Column('twitter_handle', sa.String(100), nullable=True),
        sa.Column('has_graduated', sa.Boolean(), server_default='0'),
        sa.Column('rating', sa.Float(), nullable=True),
        sa.Column('success_rate', sa.Float(), nullable=True),
        sa.Column('successful_job_count', sa.Integer(), server_default='0'),
        sa.Column('unique_buyer_count', sa.Integer(), server_default='0'),
        sa.Column('is_virtual_agent', sa.Boolean(), server_default='0'),
        sa.Column('virtual_agent_id', sa.String(20), nullable=True),
        sa.Column('total_revenue', sa.Float(), server_default='0'),
        sa.Column('owner_address', sa.String(42), nullable=True),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('prize_pool_percentage', sa.Float(), nullable=True),
        sa.Column('estimated_reward', sa.Float(), nullable=True),
        sa.Column('mcap_in_virtual', sa.Float(), nullable=True),
        sa.Column('holder_count', sa.Integer(), nullable=True),
        sa.Column('volume_24h', sa.Float(), nullable=True),
        sa.Column('total_value_locked', sa.String(50), nullable=True),
        sa.Column('snapshot_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_agdp_agents_agent_id', 'agdp_agents', ['agent_id'])
    op.create_index('ix_agdp_agents_epoch_id', 'agdp_agents', ['epoch_id'])
    op.create_index('idx_agent_epoch', 'agdp_agents', ['agent_id', 'epoch_id'])


def downgrade() -> None:
    op.drop_table('agdp_agents')
    op.drop_table('agdp_epochs')
