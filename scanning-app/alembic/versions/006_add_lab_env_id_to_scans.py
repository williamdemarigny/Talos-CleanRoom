"""Add lab_env_id column to scans table for Vulhub catalog correlation.

Revision ID: 006
Revises: 005
Create Date: 2026-04-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scans", sa.Column("lab_env_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("scans", "lab_env_id")
