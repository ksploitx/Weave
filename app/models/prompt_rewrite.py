"""PromptRewriteModel — tracks prompt optimisation/rewriting history."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PromptRewrite(Base):
    """
    Stores before/after snapshots of prompts when the system rewrites
    them, with review workflow fields for human-in-the-loop approval.
    """

    __tablename__ = "prompt_rewrites"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    target_agent: Mapped[str] = mapped_column(String(128), nullable=False)
    target_dimension: Mapped[str] = mapped_column(String(128), nullable=False)
    old_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    new_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    diff: Mapped[str] = mapped_column(Text, nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(64), nullable=False, default="pending"
    )
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    performance_delta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<PromptRewrite id={self.id} agent={self.target_agent} "
            f"status={self.status}>"
        )
