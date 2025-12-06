"""order multiple types

Revision ID: abc123def456
Revises: 040f0b9e005a
Create Date: 2025-12-06 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'abc123def456'
down_revision: Union[str, Sequence[str], None] = '040f0b9e005a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Создаем таблицу для связи заказов и типов (many-to-many)
    op.create_table(
        'order_order_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('order_type_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['order_type_id'], ['order_types.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('order_id', 'order_type_id', name='uq_order_order_type')
    )
    op.create_index(op.f('ix_order_order_types_id'), 'order_order_types', ['id'], unique=False)
    op.create_index(op.f('ix_order_order_types_order_id'), 'order_order_types', ['order_id'], unique=False)

    # Мигрируем существующие данные: переносим type_id -> order_order_types
    # Для всех заказов, у которых есть type_id, создаем запись в order_order_types
    op.execute("""
        INSERT INTO order_order_types (order_id, order_type_id, amount)
        SELECT id, type_id, amount
        FROM orders
        WHERE type_id IS NOT NULL
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # Удаляем индексы и таблицу
    op.drop_index(op.f('ix_order_order_types_order_id'), table_name='order_order_types')
    op.drop_index(op.f('ix_order_order_types_id'), table_name='order_order_types')
    op.drop_table('order_order_types')
