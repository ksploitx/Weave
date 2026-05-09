"""AgentLog model — per-agent event record within a job."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AgentLog(Base):
    """
    Records a single event produced by an agent during a job.
    Each agent event belongs to one Job.
    """

    __tablename__ = "agent_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    policy_violation: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships (lazy so async sessions stay explicit)
    job = relationship("Job", lazy="raise", back_populates=None)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AgentLog id={self.id} agent={self.agent_id} event={self.event_type}>"
        )
