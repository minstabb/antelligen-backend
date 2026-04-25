"""add importance_score to event_enrichments

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "event_enrichments",
        sa.Column("importance_score", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("event_enrichments", "importance_score")
