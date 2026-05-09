"""ToolLog model — records individual tool invocations made by agents."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ToolLog(Base):
    """
    Each row captures one tool call: the inputs sent, the output received,
    latency, and whether it was accepted.
    """

    __tablename__ = "tool_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    input: Mapped[dict | None] = mapped_column("input", JSONB, nullable=True)
    output: Mapped[dict | None] = mapped_column("output", JSONB, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job = relationship("Job", lazy="raise", back_populates=None)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ToolLog id={self.id} tool={self.tool_name} status={self.status}>"
