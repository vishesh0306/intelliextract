import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.job import Job


class JobAttempt(Base):
    __tablename__ = "job_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_llm_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_errors: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job: Mapped["Job"] = relationship(back_populates="attempts")
