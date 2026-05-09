"""initial: create all 5 tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── jobs ──────────────────────────────────────────────────────────────
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("query", sa.String(2048), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "running", "completed", "failed", "cancelled",
                name="job_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_latency_ms", sa.Integer(), nullable=False, server_default="0"),
    )

    # ── agent_logs ────────────────────────────────────────────────────────
    op.create_table(
        "agent_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("agent_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("policy_violation", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
    )

    # ── tool_logs ─────────────────────────────────────────────────────────
    op.create_table(
        "tool_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("agent_id", sa.String(128), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("input", postgresql.JSONB(), nullable=True),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── eval_runs ─────────────────────────────────────────────────────────
    op.create_table(
        "eval_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "run_type",
            sa.Enum("full", "targeted", name="run_type"),
            nullable=False,
            server_default="full",
        ),
        sa.Column("test_cases", postgresql.JSONB(), nullable=True),
        sa.Column("scores", postgresql.JSONB(), nullable=True),
        sa.Column("previous_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("delta", postgresql.JSONB(), nullable=True),
    )

    # ── prompt_rewrites ───────────────────────────────────────────────────
    op.create_table(
        "prompt_rewrites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("target_agent", sa.String(128), nullable=False),
        sa.Column("target_dimension", sa.String(128), nullable=False),
        sa.Column("old_prompt", sa.Text(), nullable=False),
        sa.Column("new_prompt", sa.Text(), nullable=False),
        sa.Column("diff", sa.Text(), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(64), nullable=False, server_default="pending"
        ),
        sa.Column("reviewer_note", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("performance_delta", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("prompt_rewrites")
    op.drop_table("eval_runs")
    op.drop_table("tool_logs")
    op.drop_table("agent_logs")
    op.drop_table("jobs")
    op.execute("DROP TYPE IF EXISTS job_status")
    op.execute("DROP TYPE IF EXISTS run_type")
