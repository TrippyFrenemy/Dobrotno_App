"""Add user_order_type_settings table and order type settings to order_types

Revision ID: user_order_type_settings
Revises: 32725b23b9d6
Create Date: 2025-12-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'user_order_type_settings'
down_revision: Union[str, Sequence[str], None] = '32725b23b9d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Добавляем nullable колонку default_employee_percent в order_types
    # NULL = использовать user.default_percent (обратная совместимость)
    op.add_column('order_types',
        sa.Column('default_employee_percent', sa.Numeric(precision=10, scale=2), nullable=True)
    )

    # Добавляем колонку include_in_employee_salary в order_types
    # True = включать в кассу для сотрудников (default для обратной совместимости)
    op.add_column('order_types',
        sa.Column('include_in_employee_salary', sa.Boolean(), nullable=False, server_default='true')
    )

    # Создаём таблицу user_order_type_settings для индивидуальных настроек
    op.create_table('user_order_type_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('order_type_id', sa.Integer(), nullable=False),
        sa.Column('custom_percent', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('is_allowed', sa.Boolean(), nullable=False, server_default='true'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['order_type_id'], ['order_types.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'order_type_id', name='uq_user_order_type_setting')
    )
    op.create_index(op.f('ix_user_order_type_settings_id'), 'user_order_type_settings', ['id'], unique=False)
    op.create_index('ix_user_order_type_settings_user_id', 'user_order_type_settings', ['user_id'], unique=False)
    op.create_index('ix_user_order_type_settings_order_type_id', 'user_order_type_settings', ['order_type_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_user_order_type_settings_order_type_id', table_name='user_order_type_settings')
    op.drop_index('ix_user_order_type_settings_user_id', table_name='user_order_type_settings')
    op.drop_index(op.f('ix_user_order_type_settings_id'), table_name='user_order_type_settings')
    op.drop_table('user_order_type_settings')
    op.drop_column('order_types', 'include_in_employee_salary')
    op.drop_column('order_types', 'default_employee_percent')
