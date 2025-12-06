"""returns require order

Revision ID: def789ghi012
Revises: abc123def456
Create Date: 2025-12-06 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'def789ghi012'
down_revision: Union[str, Sequence[str], None] = 'abc123def456'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Сделать order_id обязательным для всех возвратов
    op.alter_column('returnings', 'order_id',
                    existing_type=sa.Integer(),
                    nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Вернуть order_id обратно в nullable
    op.alter_column('returnings', 'order_id',
                    existing_type=sa.Integer(),
                    nullable=True)
