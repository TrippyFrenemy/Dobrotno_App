"""Add TikTok branches (multiple locations support)

Revision ID: tiktok_branches
Revises: user_order_type_settings
Create Date: 2025-12-29 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'tiktok_branches'
down_revision: Union[str, Sequence[str], None] = 'user_order_type_settings'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Создаём таблицу tiktok_branches
    op.create_table('tiktok_branches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_tiktok_branch_name')
    )
    op.create_index(op.f('ix_tiktok_branches_id'), 'tiktok_branches', ['id'], unique=False)

    # 2. Вставляем главную точку по умолчанию для старых данных
    op.execute("""
        INSERT INTO tiktok_branches (name, is_active, is_default)
        VALUES ('TikTok Головний', true, true)
    """)

    # 3. Создаём таблицу user_branch_assignments
    op.create_table('user_branch_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('branch_id', sa.Integer(), nullable=False),
        sa.Column('custom_percent', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_allowed', sa.Boolean(), nullable=False, server_default='true'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['branch_id'], ['tiktok_branches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'branch_id', name='uq_user_branch_assignment')
    )
    op.create_index(op.f('ix_user_branch_assignments_id'), 'user_branch_assignments', ['id'], unique=False)
    op.create_index('ix_user_branch_assignments_user_id', 'user_branch_assignments', ['user_id'], unique=False)
    op.create_index('ix_user_branch_assignments_branch_id', 'user_branch_assignments', ['branch_id'], unique=False)

    # 4. Создаём таблицу order_type_branches
    op.create_table('order_type_branches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_type_id', sa.Integer(), nullable=False),
        sa.Column('branch_id', sa.Integer(), nullable=False),
        sa.Column('is_allowed', sa.Boolean(), nullable=False, server_default='true'),
        sa.ForeignKeyConstraint(['order_type_id'], ['order_types.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['branch_id'], ['tiktok_branches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('order_type_id', 'branch_id', name='uq_order_type_branch')
    )
    op.create_index(op.f('ix_order_type_branches_id'), 'order_type_branches', ['id'], unique=False)
    op.create_index('ix_order_type_branches_order_type_id', 'order_type_branches', ['order_type_id'], unique=False)
    op.create_index('ix_order_type_branches_branch_id', 'order_type_branches', ['branch_id'], unique=False)

    # 5. Добавляем branch_id в shifts
    op.add_column('shifts',
        sa.Column('branch_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_shifts_branch_id',
        'shifts', 'tiktok_branches',
        ['branch_id'], ['id'],
        ondelete='SET NULL'
    )
    op.create_index('ix_shifts_branch_id', 'shifts', ['branch_id'], unique=False)

    # Убираем старый unique constraint на date и добавляем новый на date + branch_id
    op.drop_constraint('shifts_date_key', 'shifts', type_='unique')
    op.create_unique_constraint('uq_shift_date_branch', 'shifts', ['date', 'branch_id'])

    # 6. Добавляем branch_id в orders
    op.add_column('orders',
        sa.Column('branch_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_orders_branch_id',
        'orders', 'tiktok_branches',
        ['branch_id'], ['id'],
        ondelete='SET NULL'
    )
    op.create_index('ix_orders_branch_id', 'orders', ['branch_id'], unique=False)

    # 7. Привязываем существующие данные к главной точке
    # (опционально - можно оставить NULL, что будет означать "главная точка")
    # op.execute("""
    #     UPDATE shifts SET branch_id = (SELECT id FROM tiktok_branches WHERE is_default = true)
    #     WHERE branch_id IS NULL
    # """)
    # op.execute("""
    #     UPDATE orders SET branch_id = (SELECT id FROM tiktok_branches WHERE is_default = true)
    #     WHERE branch_id IS NULL
    # """)


def downgrade() -> None:
    """Downgrade schema."""
    # Удаляем branch_id из orders
    op.drop_index('ix_orders_branch_id', table_name='orders')
    op.drop_constraint('fk_orders_branch_id', 'orders', type_='foreignkey')
    op.drop_column('orders', 'branch_id')

    # Удаляем branch_id из shifts
    op.drop_constraint('uq_shift_date_branch', 'shifts', type_='unique')
    op.create_unique_constraint('shifts_date_key', 'shifts', ['date'])
    op.drop_index('ix_shifts_branch_id', table_name='shifts')
    op.drop_constraint('fk_shifts_branch_id', 'shifts', type_='foreignkey')
    op.drop_column('shifts', 'branch_id')

    # Удаляем order_type_branches
    op.drop_index('ix_order_type_branches_branch_id', table_name='order_type_branches')
    op.drop_index('ix_order_type_branches_order_type_id', table_name='order_type_branches')
    op.drop_index(op.f('ix_order_type_branches_id'), table_name='order_type_branches')
    op.drop_table('order_type_branches')

    # Удаляем user_branch_assignments
    op.drop_index('ix_user_branch_assignments_branch_id', table_name='user_branch_assignments')
    op.drop_index('ix_user_branch_assignments_user_id', table_name='user_branch_assignments')
    op.drop_index(op.f('ix_user_branch_assignments_id'), table_name='user_branch_assignments')
    op.drop_table('user_branch_assignments')

    # Удаляем tiktok_branches
    op.drop_index(op.f('ix_tiktok_branches_id'), table_name='tiktok_branches')
    op.drop_table('tiktok_branches')
