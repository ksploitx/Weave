"""Job model — top-level orchestration unit."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(Base):
    """Represents a single orchestration job submitted to the system."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    query: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"),
        nullable=False,
        default=JobStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Job id={self.id} status={self.status}>"
