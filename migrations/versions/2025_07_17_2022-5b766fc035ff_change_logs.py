"""Change logs

Revision ID: 5b766fc035ff
Revises: e59f498b62b2
Create Date: 2025-07-17 20:22:08.375575

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5b766fc035ff'
down_revision: Union[str, Sequence[str], None] = 'e59f498b62b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('user_logs', sa.Column('ip_address', sa.String(), nullable=True))
    op.add_column('user_logs', sa.Column('user_agent', sa.String(), nullable=True))
    op.add_column('user_logs', sa.Column('status_code', sa.Integer(), nullable=True))
    op.add_column('user_logs', sa.Column('query_string', sa.String(), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('user_logs', 'query_string')
    op.drop_column('user_logs', 'status_code')
    op.drop_column('user_logs', 'user_agent')
    op.drop_column('user_logs', 'ip_address')
    # ### end Alembic commands ###
