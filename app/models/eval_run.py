"""EvalRun model — stores evaluation run results."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RunType(str, enum.Enum):
    FULL = "full"
    TARGETED = "targeted"


class EvalRun(Base):
    """
    Captures the result of running an evaluation suite.
    Supports linking to a previous run for delta tracking.
    """

    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    run_type: Mapped[RunType] = mapped_column(
        Enum(RunType, name="run_type"),
        nullable=False,
        default=RunType.FULL,
    )
    test_cases: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    scores: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    previous_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    delta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EvalRun id={self.id} type={self.run_type}>"
