"""create event_impact_metrics

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-26

이벤트 임팩트(abnormal return) Aggregate. event_enrichments(LLM 부산물 캐시)와 분리.
- UK: (ticker, event_date, event_type, detail_hash, pre_days, post_days)
- detail_hash는 history_agent.compute_detail_hash 와 동일 알고리즘으로 enrichment 행과 join 가능
- bars_data_version 컬럼: yfinance auto_adjust 보정 후 split 시 재계산 트리거용
- 인덱스 ix_event_impact_metrics_event_lookup: history_agent 응답 빌드 시 (ticker,date,type,hash) 4-tuple 조회 최적화
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_impact_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("detail_hash", sa.String(16), nullable=False),
        sa.Column("benchmark_ticker", sa.String(20), nullable=False),
        sa.Column("pre_days", sa.Integer(), nullable=False),
        sa.Column("post_days", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("cumulative_return_pct", sa.Float(), nullable=True),
        sa.Column("benchmark_return_pct", sa.Float(), nullable=True),
        sa.Column("abnormal_return_pct", sa.Float(), nullable=True),
        sa.Column(
            "sample_completeness",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("bars_data_version", sa.String(64), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "ticker",
            "event_date",
            "event_type",
            "detail_hash",
            "pre_days",
            "post_days",
            name="uq_event_impact_metrics_key",
        ),
    )
    op.create_index(
        "ix_event_impact_metrics_event_lookup",
        "event_impact_metrics",
        ["ticker", "event_date", "event_type", "detail_hash"],
    )
    op.create_index(
        "ix_event_impact_metrics_event_date",
        "event_impact_metrics",
        ["event_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_event_impact_metrics_event_date", table_name="event_impact_metrics"
    )
    op.drop_index(
        "ix_event_impact_metrics_event_lookup", table_name="event_impact_metrics"
    )
    op.drop_table("event_impact_metrics")
