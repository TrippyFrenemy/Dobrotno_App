"""add percent

Revision ID: 2f5f368c7739
Revises: e1281c2ffbc0
Create Date: 2025-07-13 19:14:39.717258

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f5f368c7739'
down_revision: Union[str, Sequence[str], None] = 'e1281c2ffbc0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('users', sa.Column('default_percent', sa.Numeric(precision=10, scale=2), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('users', 'default_percent')
    # ### end Alembic commands ###
